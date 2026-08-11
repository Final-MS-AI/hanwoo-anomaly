import os, json, numpy as np
ROOT = os.path.expanduser("~/data/zenodo6324361/BeefCattle_Muzzle_Individualized")
cows = sorted(d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d)))
print("전체 개체:", len(cows))
rng = np.random.RandomState(42)
cows_sh = list(cows); rng.shuffle(cows_sh)
unseen = sorted(cows_sh[:67])
print("미학습 평가 개체:", len(unseen), "→", unseen[:3], "...")
json.dump(unseen, open(os.path.expanduser("~/muzzle_api/eval_cows.json"), "w"))
