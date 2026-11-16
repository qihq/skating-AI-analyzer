"""Read-only legacy geometry recovery through the real endpoint."""
import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from PIL import Image
from app.models import Analysis
from app.routers import analysis as router
from app.schemas import PoseResponse

class GeometryTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_geometry_contract_and_fail_closed_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'frames').mkdir()
            Image.new('RGB',(800,400)).save(root/'frames'/'generic.jpg')
            timeline={'schema_version':'source-timeline.v1','source_video_hash':'a'*64,'width':400,'height':800,'rotation_degrees':0}
            manifest={'schema_version':'analysis_media.v1','source_timeline':timeline}
            row=Analysis(id='generic',status='awaiting_target_selection',action_type='跳跃',pipeline_version='legacy/local-r1',video_path=str(root/'source.mp4'),pose_data={'connections':[],'frames':[{'frame':'generic.jpg','keypoints':[]}]},frame_motion_scores={'full_size':'800x400','selection_strategy':'motion_weighted','video_identity':{'sha256':'a'*64}})
            before=copy.deepcopy(row.pose_data); session=AsyncMock(); session.get.return_value=row
            async def fetch():
                (root/'media-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
                with patch.object(router,'_frames_dir_for_analysis',return_value=root/'frames'),patch.object(router,'extract_pose',side_effect=AssertionError('no inference')):
                    response=await router.get_analysis_pose('generic',session)
                return PoseResponse.model_validate(response.model_dump()).model_dump()
            response=await fetch()
            self.assertIsNotNone(response.get('geometry'))
            self.assertEqual(response['geometry']['content_rect'],{'x':300,'y':0,'width':200,'height':400})
            self.assertEqual(response['geometry']['provenance'],'saved_metadata_verified_frames')
            for field,value in [('source_video_hash','b'*64),('rotation_degrees',90),('width',0),('width',True)]:
                original=timeline[field]; timeline[field]=value
                self.assertIsNone((await fetch()).get('geometry')); timeline[field]=original
            for pipeline in [None,'unknown']:
                row.pipeline_version=pipeline; self.assertIsNone((await fetch()).get('geometry'))
            row.pipeline_version='legacy/local-r1'
            Image.new('RGB',(400,400)).save(root/'frames'/'generic.jpg')
            self.assertIsNone((await fetch()).get('geometry'))
            (root/'media-manifest.json').unlink()
            with patch.object(router,'_frames_dir_for_analysis',return_value=root/'frames'):
                self.assertIsNone((await router.get_analysis_pose('generic',session)).model_dump().get('geometry'))
            self.assertEqual(row.pose_data,before); session.commit.assert_not_awaited()

    async def test_general_legacy_scale_and_chroma_pad_geometry(self):
        from app.services.pose_geometry import recover_pose_geometry
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'frames').mkdir()
            for source,size,expected in [((800,400),(400,800),{'x':0,'y':300,'width':400,'height':200}),((600,300),(600,300),{'x':0,'y':0,'width':600,'height':300}),((400,800),(802,400),{'x':300,'y':0,'width':200,'height':400})]:
                with self.subTest(source=source,size=size):
                    Image.new('RGB',size).save(root/'frames'/'generic.jpg')
                    timeline={'schema_version':'source-timeline.v1','source_video_hash':'a'*64,'width':source[0],'height':source[1],'rotation_degrees':0}
                    (root/'media-manifest.json').write_text(json.dumps({'schema_version':'analysis_media.v1','source_timeline':timeline}),encoding='utf-8')
                    row=Analysis(id='shape',pipeline_version='legacy/local-r1',video_path=str(root/'source.mp4'),pose_data={'frames':[{'frame':'generic.jpg','keypoints':[]}]},frame_motion_scores={'full_size':str(size[0])+'x'+str(size[1]),'selection_strategy':'motion_weighted','video_identity':{'sha256':'a'*64}})
                    geometry,reason=recover_pose_geometry(row,root/'frames')
                    self.assertIsNone(reason);self.assertEqual(geometry['content_rect'],expected)
                    row.pose_data={'frames':[{'frame':'../elsewhere.jpg','keypoints':[]}]}
                    self.assertIsNone(recover_pose_geometry(row,root/'frames')[0])
