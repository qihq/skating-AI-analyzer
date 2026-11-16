"""Offline body geometry: synthetic truth, real JPEG encoding, no models/video."""
import copy
import cv2
import numpy as np
import pytest
from app.services.person_tracker import PersonBBoxTracker
from test_tracking_appearance_contract import scene, BOX, compatible
from test_tracking_reference_contract import patterned_case, assert_reference_saved_consumer_chain


@pytest.mark.parametrize('factor', [1.25, 1.5])
def test_body_region_survives_box_width_and_background_share(factor):
    tracker = PersonBBoxTracker.__new__(PersonBBoxTracker)
    image = scene()
    cx = (BOX[0]+BOX[2])/2
    half = (BOX[2]-BOX[0])*factor/2
    expanded = (cx-half, BOX[1], cx+half, BOX[3])
    frozen = copy.deepcopy((image, expanded))
    a = tracker._independent_identity_signature(image, BOX)
    b = tracker._independent_identity_signature(image, expanded)
    assert a is not None and b is not None
    assert compatible(a,b)
    assert a['geometry']['feature_xyxy'] == b['geometry']['feature_xyxy']
    np.testing.assert_array_equal(image, frozen[0])
    assert expanded == frozen[1]


@pytest.mark.parametrize('kind', ['different','mirror','occluded','uniform'])
def test_body_geometry_keeps_different_layout_and_insufficient_evidence_rejected(kind):
    tracker = PersonBBoxTracker.__new__(PersonBBoxTracker)
    a = tracker._independent_identity_signature(scene(), BOX)
    b = tracker._independent_identity_signature(scene(kind), (61,50,211,214))
    assert not compatible(a,b)


@pytest.mark.parametrize('invalid', [float('nan'),float('inf'),float('-inf')])
def test_nonfinite_geometry_is_missing_evidence(invalid):
    tracker = PersonBBoxTracker.__new__(PersonBBoxTracker)
    assert tracker._independent_identity_signature(scene(),(invalid,50,186,214)) is None


def body_case(tmp_path, monkeypatch, kind, origin):
    """Arm construction and detector truth are fixed before feature comparison."""
    write = cv2.imwrite
    counter = [0]
    def save(filename, image, *args):
        i = counter[0]; counter[0] += 1
        if i >= 6 and kind in ('arms','arms_jitter'):
            # Symmetric arm changes occupy five of 69 torso rows. The torso
            # pattern and its left/right order remain unchanged by construction.
            image[84:89,88:118] = [96,99,98]
            image[84:89,174:204] = [96,99,98]
        return write(filename,image,*args)
    with monkeypatch.context() as writing:
        writing.setattr(cv2,'imwrite',save)
        result = patterned_case(tmp_path,monkeypatch,'same',origin,
                                colours=[[27,29,30],[96,99,98],[183,185,186]])
    pool,frames,motion,lock,calls,detections = result
    for i in range(6,12):
        # Diagnostic synthetic detections only, never a cached real receipt.
        dx = (-1.,0.,1.)[i%3] if kind == 'arms_jitter' else 0.
        detections[i] = [(80.+dx,44.,212.+dx,200.,.95)]
        if kind == 'nested':
            detections[i].append((81.+dx,44.,211.+dx,200.,.95))
    return pool,frames,motion,lock,calls,detections


@pytest.mark.parametrize('kind',['width','arms','arms_jitter','nested'])
def test_body_geometry_saved_consumers(tmp_path,monkeypatch,kind):
    assert_reference_saved_consumer_chain(tmp_path,monkeypatch,kind,
        case_factory=body_case,positives={'width','arms','arms_jitter'},
        evidence_prefix='body-geometry')


@pytest.mark.parametrize("box", [(0, 0, 40, 200), (280, 0, 320, 200)])
def test_body_geometry_rejects_corridor_outside_image(box):
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    region = PersonBBoxTracker._independent_body_region(image, box)
    assert region["status"] == "region_insufficient"
    assert "feature_xyxy" not in region


@pytest.mark.parametrize("scale", [.8, 1., 1.3])
@pytest.mark.parametrize("pattern", [0, 1])
@pytest.mark.parametrize("change", ["left_right", "top_bottom", "outer_only", "one_sided"])
def test_outer_identity_layout_survives_inner_surface(scale, pattern, change):
    """Independent synthetic truth: central textile identical, outer panels differ.

    Vary dimensions, central texture and panel colours before calling production.
    A same-person control must remain informative and compatible in every case.
    """
    box = (56., 44., 236., 200.)
    def image(changed):
        im = np.full((240,640,3),214,np.uint8)
        im[44:200,56:236] = 40
        yy,xx = np.mgrid[:69,:32]
        labels = (np.where(yy < 30,np.where(xx < 12,0,1),np.where(xx < 23,2,0))
                  if pattern == 0 else np.where(xx < 15,np.where(yy < 40,2,0),1))
        im[72:141,130:162] = np.asarray([[27,29,30],[96,99,98],[183,185,186]],np.uint8)[labels]
        colours = ([[220,70,20],[20,170,230]] if pattern == 0 else [[80,80,80],[165,165,165]])
        if change == "top_bottom":
            ordered = colours[::-1] if changed else colours
            for l,r in [(90,106),(186,202)]:
                im[72:106,l:r],im[106:141,l:r] = ordered[0],ordered[1]
        else:
            ordered = colours[::-1] if changed else colours
            if changed and change == "outer_only":
                ordered = [[130,40,170],[20,110,100]]
            im[72:141,90:106],im[72:141,186:202] = ordered
        if change == "one_sided":
            im[72:141,186:202] = 40
            ordered = colours[::-1] if changed else colours
            im[72:106,90:106],im[106:141,90:106] = ordered
        return cv2.resize(im,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST)
    tracker = PersonBBoxTracker.__new__(PersonBBoxTracker)
    scaled = tuple(v*scale for v in box)
    a = tracker._independent_identity_signature(image(False),scaled)
    same = tracker._independent_identity_signature(image(False),scaled)
    b = tracker._independent_identity_signature(image(True),scaled)
    assert a is not None and same is not None and b is not None
    assert compatible(a,same)
    assert not compatible(a,b)
    # Outlying evidence must actually lie in the final feature region.
    x0,_,x1,_ = a['geometry']['feature_xyxy']
    assert x0 <= 92*scale
    if change != "one_sided":
        assert x1 >= 200*scale
