"""Deterministic appearance tests; no model or video entry points."""
import cv2
import numpy as np
import pytest
from app.services.person_tracker import PersonBBoxTracker


def scene(kind='base'):
    image=np.full((240,320,3),214,np.uint8)
    yy,xx=np.mgrid[:72,:64];u=(xx+.5)/64;v=(yy+.5)/72
    labels=np.where(v<.43,np.where(u<.34,0,1),np.where(u<.73,2,0))
    if kind=='different': labels=np.where(v<.43,np.where(u<.72,1,0),np.where(u<.42,0,2))
    if kind=='mirror': labels=labels[:,::-1]
    if kind=='occluded': labels[:,:48]=0
    palette=np.array([[27,29,30],[96,99,98],[183,185,186]],float)
    patch=palette[labels];patch+=(((xx//5+yy//6)%2)*2-1)[:,:,None]*2
    if kind=='channel_noise': patch=patch[:,:,[2,0,1]]
    if kind=='brightness': patch*=.85
    if kind=='local_color': patch[:18,:20]+=np.array([2,-1,1])
    if kind=='uniform':patch[:]=70
    image[80:152,104:168]=np.clip(patch,0,255).astype(np.uint8)
    if kind=='jpeg':
        ok,data=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,88]);assert ok
        image=cv2.imdecode(data,cv2.IMREAD_COLOR)
    return image


BOX=(86,50,186,214)


def signature(kind,box=BOX):
    return PersonBBoxTracker.__new__(PersonBBoxTracker)._independent_identity_signature(scene(kind),box)


def compatible(a,b):
    if a is None or b is None:return False
    s=PersonBBoxTracker._independent_identity_scores(a,b)
    return (float(a['pooled']@b['pooled'])>=.90 and s['pooled_cosine']>=.90 and
            s['layout_mean']>=.90 and s['layout_lower_quartile']>=.75 and s['structure_correlation']>=.85)


@pytest.mark.parametrize('kind',['channel_noise','brightness','local_color','jpeg','jitter'])
def test_neutral_textile_supported_perturbations(kind):
    a=signature('base');b=signature(kind if kind!='jitter' else 'base',
                                    (87,50.5,187,214.5) if kind=='jitter' else BOX)
    assert a is not None and b is not None
    assert compatible(a,b),(kind,PersonBBoxTracker._independent_identity_scores(a,b))


@pytest.mark.parametrize('kind',['different','mirror','occluded','uniform'])
def test_same_background_is_not_target_identity(kind):
    assert not compatible(signature('base'),signature(kind))


def test_tiny_crop_has_no_identity_evidence():
    assert signature('base',(104,80,120,110)) is None


NEUTRAL_POSITIVE={'same','jitter','mild_crop','scale','brightness','pose','channel_noise','local_color','jpeg'}


def neutral_case(tmp_path,monkeypatch,kind,origin):
    from test_tracking_reference_contract import patterned_case
    def perturb(patch,index):
        if kind=='channel_noise':return patch[:,:,[2,0,1]] if index%2 else patch
        if kind=='local_color':
            patch=patch.copy();patch[:12,:16]+=np.array([2,-1,1])
        return patch
    return patterned_case(tmp_path,monkeypatch,
        'same' if kind in ('channel_noise','local_color','jpeg') else kind,origin,
        colours=[[27,29,30],[96,99,98],[183,185,186]],perturb=perturb,
        jpeg_quality=88 if kind=='jpeg' else 100)


@pytest.mark.parametrize('kind',sorted(NEUTRAL_POSITIVE)+[
    'vertical_swap','horizontal_swap','alternating','permuted','different','gray',
    'background_only','occluded','ambiguous','insufficient_reference','after_switch',
    'large_shift','tiny'])
def test_neutral_saved_consumer_chain(tmp_path,monkeypatch,kind):
    from test_tracking_reference_contract import assert_reference_saved_consumer_chain
    assert_reference_saved_consumer_chain(tmp_path,monkeypatch,kind,
        case_factory=neutral_case,positives=NEUTRAL_POSITIVE,evidence_prefix='appearance')


def test_reliable_chromatic_difference_is_not_erased_by_equal_luminance():
    """Identical grayscale/layout cannot replace reliable clothing colour."""
    yy,xx=np.mgrid[:72,:64];u=(xx+.5)/64;v=(yy+.5)/72
    labels=np.where(v<.43,np.where(u<.34,0,1),np.where(u<.73,2,0))
    images=[]
    for palette in ([[0,0,100],[0,85,0],[255,70,0]],
                    [[0,34,34],[71,71,0],[169,0,169]]):
        image=scene();image[80:152,104:168]=np.asarray(palette,np.uint8)[labels]
        images.append(image)
    assert np.array_equal(cv2.cvtColor(images[0],cv2.COLOR_BGR2GRAY),
                          cv2.cvtColor(images[1],cv2.COLOR_BGR2GRAY))
    tracker=PersonBBoxTracker.__new__(PersonBBoxTracker)
    a,b=[tracker._independent_identity_signature(image,BOX) for image in images]
    assert a is not None and b is not None
    scores=tracker._independent_identity_scores(a,b)
    assert scores['structure_correlation']>.99
    assert scores['pooled_cosine']<.90 and scores['layout_mean']<.90
    assert not compatible(a,b)
