import unittest
from ai_scoring.services.evaluation import evaluate

class EvaluationTests(unittest.TestCase):
    def test_only_independent_truth_and_missing_count_fail(self):
        records=[{'type':'prediction','payload':{'predictionId':'p','status':'available','points':15}}]
        for index,source in enumerate(('manual','ai_selected','manual')):
            entry=str(index)
            records.append({'type':'event','payload':{'event':{'type':'break_committed','entryId':entry,'source':source,'submittedPoints':15,'predictionId':'p' if index < 2 else None},'comparison':{'boundaryUncertain':False}}})
        result=evaluate(records)
        self.assertIsNone(result['exactAccuracy'])
        for entry in ('0','1','2'):
            records.append({'type':'review','payload':{'entryId':entry,'independent':True,'evidenceSufficient':True,'eligible':True,'actualPoints':15}})
        result=evaluate(records)
        self.assertEqual(result['exactAccuracy'],2/3)
        self.assertEqual(result['missingPredictions'],1)
        self.assertFalse(result['rolloutApproved'])
    def test_undo_requires_resolved_review(self):
        records=[{'type':'event','payload':{'event':{'type':'break_committed','entryId':'e','predictionId':None},'comparison':{}}},
                 {'type':'event','payload':{'event':{'type':'undo','entryId':'e'}}},
                 {'type':'review','payload':{'entryId':'e','eligible':True,'independent':True,'evidenceSufficient':True,'actualPoints':1}}]
        self.assertEqual(evaluate(records)['exclusions'],{'unresolved_revision':1})
    def test_review_must_follow_latest_revision(self):
        records=[{'type':'event','payload':{'event':{'type':'break_committed','entryId':'e','predictionId':None},'comparison':{}}},
                 {'type':'review','payload':{'entryId':'e','eligible':True,'independent':True,'evidenceSufficient':True,'actualPoints':1,'resolvesRevision':True}},
                 {'type':'event','payload':{'event':{'type':'correction','entryId':'e'}}}]
        self.assertEqual(evaluate(records)['eligibleReviewed'],0)
        records.append({'type':'review','payload':{'entryId':'e','eligible':True,'independent':True,'evidenceSufficient':True,'actualPoints':1,'resolvesRevision':True}})
        self.assertEqual(evaluate(records)['eligibleReviewed'],1)
    def test_correction_affected_commit_requires_resolution(self):
        records=[{'type':'event','payload':{'event':{'type':'break_committed','entryId':'e','predictionId':None,'correctionAffected':True},'comparison':{}}},
                 {'type':'review','payload':{'entryId':'e','eligible':True,'independent':True,'evidenceSufficient':True,'actualPoints':1}}]
        self.assertEqual(evaluate(records)['eligibleReviewed'],0)
    def test_evidence_required_and_heldout_reported_separately(self):
        records=[{'type':'event','payload':{'event':{'type':'break_committed','entryId':'e','predictionId':None},'comparison':{}}},
                 {'type':'review','payload':{'entryId':'e','eligible':True,'independent':True,'actualPoints':1}}]
        self.assertEqual(evaluate(records)['exclusions'],{'insufficient_review_evidence':1})
        records[-1]['payload'].update(evidenceSufficient=True,heldOut=True)
        result=evaluate(records)
        self.assertEqual(result['heldOutReviewed'],1)
        self.assertEqual(result['heldOutExactAccuracy'],0)
        self.assertFalse(result['rolloutApproved'])
