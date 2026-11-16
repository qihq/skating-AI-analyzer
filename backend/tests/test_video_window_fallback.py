"""R1-RV-03: synthetic media only, real ffmpeg and production sampling entrypoint."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import cv2
from app.services import video


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires real ffmpeg/ffprobe')
class WindowFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'two-color.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', 'color=c=red:s=320x240:r=10:d=2',
                        '-f', 'lavfi', '-i', 'color=c=blue:s=320x240:r=10:d=2',
                        '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]',
                        '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(self.source)],
                       check=True, capture_output=True)
        self.frames = self.root / 'frames'
        self.frames.mkdir()

    def window(self, start=2., end=4.):
        return video.VideoInputWindow(source_duration_sec=4., input_window_start_sec=start,
            input_window_end_sec=end, input_window_duration_sec=end-start,
            input_window_mode='manual_window' if start else 'full_context',
            input_window_truncated=False, input_window_reason='synthetic regression')

    async def extract(self, start=2., end=4.):
        return await video.extract_motion_sampled_frames(self.source, self.frames, '跳跃', 'jump',
                                                       input_window=self.window(start, end))

    def check_fallback(self, paths, payload, meta):
        self.assertEqual(payload['selection_strategy'], 'uniform_window_fallback')
        self.assertEqual(payload['timestamp_basis'], 'decoded_source_pts_time')
        self.assertEqual(payload['source_index_basis'], 'uniform_extraction_ordinal')
        self.assertEqual(len(paths), len(payload['selected']))
        self.assertEqual(payload['resolved_sample_count'], len(paths))
        self.assertEqual(payload['sample_count'], len(paths))
        self.assertEqual(payload['window_start'], 2.)
        self.assertEqual(payload['window_end'], 4.)
        self.assertEqual(meta.action_window_start, 2.)
        self.assertEqual(meta.action_window_end, 4.)
        self.assertEqual(meta.effective_fps, round((len(paths)-1)/2, 3))
        self.assertEqual(payload['effective_fps'], meta.effective_fps)
        self.assertEqual(payload['top_motion_peaks'], [])
        self.assertEqual(payload['scores'], [])
        self.assertEqual(set(paths), set(self.frames.glob('frame_*.jpg')))
        timestamps = video.build_timestamp_map(payload)
        for path, record in zip(paths, payload['selected']):
            self.assertEqual(path.stem, record['frame_id'])
            i = int(path.stem.split('_')[1])-1
            self.assertEqual(record['source_sample_index'], i)
            self.assertEqual(record['source_thumb_index'], i)
            self.assertAlmostEqual(record['timestamp'], 2+i/10, places=5)
            self.assertEqual(timestamps[path.stem], record['timestamp'])
            self.assertLess(record['timestamp'], 4.)
            b, g, r = cv2.imread(str(path)).mean(axis=(0,1))
            self.assertGreater(b, r+100, 'frame outside selected blue window')

    async def test_real_ffmpeg_natural_eof_preserves_window_and_decoded_time(self):
        # No patches: the precise seek at 3.917 naturally succeeds without a file.
        paths, payload, meta = await self.extract()
        self.check_fallback(paths, payload, meta)
        self.assertEqual(len(paths), 20)
        self.assertEqual(payload['selected'][-1]['timestamp'], 3.9)

    async def test_downsampling_keeps_original_extraction_indices_and_pts(self):
        # Config override only in this test; decoding and business function remain real.
        with (patch.object(video, 'get_sampling_density', return_value=(5, 5, 'test_cap')),
              patch.object(video, '_extract_full_frame_at', AsyncMock())):
            result = await self.extract()
        self.check_fallback(*result)
        paths, payload, _ = result
        self.assertEqual(len(paths), 5)
        self.assertEqual(payload['uniform_frame_count'], 20)
        self.assertEqual(payload['selected'][-1]['source_sample_index'], 19)
        self.assertEqual(payload['selected'][-1]['timestamp'], 3.9)
        self.assertTrue(payload['coverage_gaps'])

    async def test_success_without_file_falls_back(self):
        with patch.object(video, '_extract_full_frame_at', AsyncMock()):
            self.check_fallback(*(await self.extract()))

    async def test_success_with_empty_file_falls_back(self):
        async def empty(source, timestamp, target):
            target.touch()
        with patch.object(video, '_extract_full_frame_at', side_effect=empty):
            self.check_fallback(*(await self.extract()))

    async def test_thumbnail_failure_does_not_widen_manual_window(self):
        with patch.object(video, '_extract_thumbnails_in_window', AsyncMock(side_effect=RuntimeError('decode'))):
            self.check_fallback(*(await self.extract()))

    async def test_no_decodable_frames_has_readable_failure(self):
        with self.assertRaisesRegex(RuntimeError, '所选视频窗口内没有可解码的有效帧'):
            await self.extract(5., 6.)

    async def test_normal_full_context_precise_path_is_preserved(self):
        paths, payload, meta = await self.extract(0., 4.)
        self.assertEqual(payload['selection_strategy'], 'motion_weighted')
        self.assertEqual(payload['timestamp_basis'], 'requested_source_seek_time')
        self.assertGreater(len(paths), 0)
        for path, rec in zip(paths, payload['selected']):
            self.assertEqual(path.stem, rec['frame_id'])
            self.assertAlmostEqual(rec['timestamp'], rec['source_thumb_index']/payload['frame_rate'], places=2)
            self.assertTrue(path.stat().st_size)
        b, g, r = cv2.imread(str(paths[0])).mean(axis=(0,1))
        self.assertGreater(r, b+100)


if __name__ == '__main__':
    unittest.main()
