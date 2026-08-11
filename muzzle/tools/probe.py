import onnxruntime as ort, numpy as np
s = ort.InferenceSession("/home/azureuser/models/muzzle/weights/muzzle_encoder.onnx",
                         providers=["CPUExecutionProvider"])
for i in s.get_inputs():  print("INPUT :", i.name, i.shape, i.type)
for o in s.get_outputs(): print("OUTPUT:", o.name, o.shape, o.type)
x = np.random.randn(1,3,224,224).astype(np.float32)
y = s.run(None, {s.get_inputs()[0].name: x})[0]
print("실제 출력:", y.shape, "| L2 norm:", float(np.linalg.norm(y[0])))
