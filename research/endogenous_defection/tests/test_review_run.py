import pytest

from research.endogenous_defection.io import dump, seal, verify
from research.endogenous_defection.review_run import review, wait_for_bundle


def test_running_bundle_cannot_be_analyzed(tmp_path):
    root=tmp_path/'run'; bundle=root/'bundle'; bundle.mkdir(parents=True)
    dump(bundle/'bundle.json',{'status':'running'})
    out=tmp_path/'review'
    with pytest.raises(TimeoutError):
        review(root,out)
    assert not out.exists()


def test_complete_seal_can_be_waited_for_and_nested_review_is_blocked(tmp_path):
    root=tmp_path/'run'; bundle=root/'bundle'; bundle.mkdir(parents=True)
    dump(bundle/'bundle.json',{'status':'complete'})
    seal(bundle)
    actual,meta=wait_for_bundle(root,0)
    assert actual==bundle and meta['status']=='complete'
    with pytest.raises(ValueError,match='outside'):
        review(root,bundle/'review')
    verify(bundle)


def test_changed_evidence_is_rejected_before_output_creation(tmp_path):
    bundle=tmp_path/'bundle'; bundle.mkdir()
    dump(bundle/'bundle.json',{'status':'complete'})
    seal(bundle)
    (bundle/'extra.txt').write_text('changed')
    with pytest.raises(ValueError,match='checksums'):
        review(bundle,tmp_path/'review')
    assert not (tmp_path/'review').exists()
