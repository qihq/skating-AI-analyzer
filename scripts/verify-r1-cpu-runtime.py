"""Run in Linux CPU runtime. Synthetic operator evidence is not person accuracy evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
results = {'platform': platform.platform(), 'machine': platform.machine(), 'python': sys.version,
           'scope': 'synthetic CPU operators and bundled MediaPipe graph; no human samples',
           'target_nas_verified': False, 'checks': [], 'network_attempts': []}

def audit(event, values):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        results['network_attempts'].append({'event': event, 'address': repr(values[1:] if event == 'socket.connect' else values)})
        raise RuntimeError('runtime smoke forbids network attempts')
sys.addaudithook(audit)

def check(name, fn):
    started = time.monotonic()
    try:
        evidence = fn()
        results['checks'].append({'name': name, 'status': 'passed', 'seconds': round(time.monotonic()-started, 3), 'evidence': evidence})
    except Exception as exc:
        results['checks'].append({'name': name, 'status': 'failed', 'error': repr(exc)})
    print(json.dumps(results['checks'][-1]), flush=True)
    (args.output/'runtime-smoke.json').write_text(json.dumps(results, indent=2))

def torch_ops():
    import torch
    import torchvision
    from torchvision.ops import nms
    assert torch.version.cuda is None
    matrix=torch.mm(torch.ones((8,8)),torch.ones((8,8)))
    assert matrix.sum().item()==512
    keep=nms(torch.tensor([[0.,0.,10.,10.],[1.,1.,9.,9.],[30.,30.,40.,40.]]),torch.tensor([.9,.8,.7]),.5)
    assert keep.tolist()==[0,2]
    return {'torch':torch.__version__,'torchvision':torchvision.__version__,'nms_keep':keep.tolist(),'cpu_capability':torch.backends.cpu.get_cpu_capability()}

def video_ops():
    import cv2
    video=args.output/'empty.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=gray:s=320x240:r=10:d=2','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    capture=cv2.VideoCapture(str(video));count=0
    while True:
        ok,frame=capture.read()
        if not ok:break
        count+=1
        if count==1:cv2.imwrite(str(args.output/'empty-frame.png'),frame)
    capture.release();assert count==20,count
    return {'opencv':cv2.__version__,'decoded_frames':count,'codec':metadata['streams'][0]['codec_name'],'sha256':hashlib.sha256(video.read_bytes()).hexdigest()}

def mediapipe_ops():
    import cv2
    import mediapipe as mp
    image=cv2.cvtColor(cv2.imread(str(args.output/'empty-frame.png')),cv2.COLOR_BGR2RGB)
    with mp.solutions.pose.Pose(static_image_mode=True,model_complexity=1,enable_segmentation=False,min_detection_confidence=.5) as pose:
        outcome=pose.process(image)
    assert outcome.pose_landmarks is None
    models=[]
    for rel in ['modules/pose_landmark/pose_landmark_full.tflite','modules/pose_detection/pose_detection.tflite']:
        path=Path(mp.__file__).parent/rel
        models.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    return {'mediapipe':mp.__version__,'pose_graph_process':True,'person_detected':False,'models':models,
            'jax_imported': 'jax' in sys.modules, 'jaxlib_imported': 'jaxlib' in sys.modules,
            'limitation':'Blank frame executes pose graph/detector; no positive landmark or person accuracy assertion.'}

def mediapipe_landmark_roi_ops():
    import mediapipe as mp
    import numpy as np
    from mediapipe.framework.formats import rect_pb2
    from mediapipe.python._framework_bindings import resource_util
    resource_util.set_resource_dir(str(Path(mp.__file__).parent.parent))
    config = '''input_stream: "image"
input_stream: "roi"
output_stream: "landmarks"
node { calculator: "PoseLandmarkByRoiCpu"
 input_stream: "IMAGE:image" input_stream: "ROI:roi"
 output_stream: "LANDMARKS:landmarks"
}'''
    template=mp.CalculatorGraph(graph_config=config)
    score_stream='poselandmarkbyroicpu__tensorstoposelandmarksandsegmentation__pose_presence_score'
    expanded=template.text_config+'\noutput_stream: "'+score_stream+'"\n'
    graph=mp.CalculatorGraph(graph_config=expanded)
    scores=[]
    graph.observe_output_stream(score_stream,lambda name,packet:scores.append(mp.packet_getter.get_float(packet)))
    graph.start_run()
    graph.add_packet_to_input_stream('image',mp.packet_creator.create_image_frame(np.zeros((256,256,3),dtype=np.uint8),image_format=mp.ImageFormat.SRGB).at(0))
    graph.add_packet_to_input_stream('roi',mp.packet_creator.create_proto(rect_pb2.NormalizedRect(x_center=.5,y_center=.5,width=1,height=1,rotation=0)).at(0))
    graph.close_all_packet_sources();graph.wait_until_done()
    assert len(scores)==1 and 0<=scores[0]<=1,scores
    return {'landmark_model_executed':True,'pose_presence_scores':scores,
            'input':'black synthetic frame with supplied full-frame ROI',
            'limitation':'native model execution only; no person, target tracking, positive pose or accuracy claim'}

def yolo_architecture_ops():
    import numpy as np
    from ultralytics import YOLO
    model=YOLO('yolov8n.yaml')
    outcome=model.predict(np.zeros((240,320,3),dtype=np.uint8),device='cpu',imgsz=320,verbose=False)
    assert len(outcome)==1
    return {'forward_executed':True,'weights':'random architecture initialization ONLY',
            'pretrained_detection':'not_run: official model provenance still required'}

check('torch_cpu_and_torchvision_nms',torch_ops)
check('ffmpeg_ffprobe_opencv_decode',video_ops)
check('mediapipe_bundled_pose_graph',mediapipe_ops)
check('mediapipe_landmark_model_supplied_synthetic_roi',mediapipe_landmark_roi_ops)
check('ultralytics_architecture_forward_only',yolo_architecture_ops)
results['external_network_attempts_count']=len(results['network_attempts'])
(args.output/'runtime-smoke.json').write_text(json.dumps(results,indent=2))
raise SystemExit(1 if results['network_attempts'] or any(c['status']!='passed' for c in results['checks']) else 0)
