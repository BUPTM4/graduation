import AnomalyCLIP_lib
import torch
import argparse
import torch.nn.functional as F
from prompt_ensemble import AnomalyCLIP_PromptLearner
from PIL import Image
import os
import numpy as np
from utils import get_transform, normalize
from scipy.ndimage import gaussian_filter
import base64
from flask import Flask, request, jsonify
from flask_cors import CORS
import cv2
import time

app = Flask(__name__)
CORS(app)

print("=" * 50)
print("正在初始化模型...")

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"计算设备: {device}")
if device == "cuda":
    print(f"GPU型号: {torch.cuda.get_device_name(0)}")
    print(f"GPU显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

def setup_model():
    AnomalyCLIP_parameters = {"Prompt_length": 12, "learnabel_text_embedding_depth": 9, "learnabel_text_embedding_length": 4}
    model, _ = AnomalyCLIP_lib.load("ViT-L/14@336px", device='cpu', design_details=AnomalyCLIP_parameters)
    model.eval()
    
    prompt_learner = AnomalyCLIP_PromptLearner(model, AnomalyCLIP_parameters)
    model_path = "./checkpoints/9_12_4_multiscale/epoch_15.pth"
    if not os.path.exists(model_path):
        model_path = "./checkpoints/9_12_4_multiscale_visa/epoch_15.pth"
        if not os.path.exists(model_path):
            raise FileNotFoundError("Model checkpoint not found. Please check the path.")
    checkpoint = torch.load(model_path, map_location='cpu')
    prompt_learner.load_state_dict(checkpoint["prompt_learner"])
    
    model.to(device)
    prompt_learner.to(device)
    model.visual.DAPM_replace(DPAM_layer=20)
    
    prompts, tokenized_prompts, compound_prompts_text = prompt_learner(cls_id=None)
    text_features = model.encode_text_learn(prompts, tokenized_prompts, compound_prompts_text).float()
    text_features = torch.stack(torch.chunk(text_features, dim=0, chunks=2), dim=1)
    text_features = text_features / text_features.norm(dim=-1, keepdim=True)
    text_features = text_features.to(device)
    
    return model, prompt_learner, text_features, device

model, prompt_learner, text_features, device = setup_model()
print("模型初始化完成!")
print("=" * 50)

# 图像预处理函数
def preprocess_image(image_path, material):
    """
    图像预处理函数，包含CLAHE光照均衡和高斯-中值联合滤波
    """
    img = cv2.imread(image_path)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    
    # CLAHE光照均衡
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    lab = cv2.merge((cl, a, b))
    img = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    
    # 高斯-中值联合滤波
    img = cv2.GaussianBlur(img, (5, 5), 0)
    img = cv2.medianBlur(img, 5)
    
    base_name = os.path.basename(image_path)
    dir_name = os.path.dirname(image_path)
    name_without_ext, ext = os.path.splitext(base_name)
    preprocessed_base_name = f"{name_without_ext}_preprocessed{ext}"
    preprocessed_path = os.path.join(dir_name, preprocessed_base_name)
    cv2.imwrite(preprocessed_path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    
    return preprocessed_path

# 检测函数
def detect_anomaly(image_path, material='cotton', precision='precision'):
    img_size = 518
    features_list = [6, 12, 18, 24]
    feature_map_layer = [0, 1, 2, 3]
    sigma = 4
    
    preprocessed_path = preprocess_image(image_path, material)
    
    preprocess, target_transform = get_transform(argparse.Namespace(image_size=img_size))
    
    img = Image.open(preprocessed_path)
    img = preprocess(img)
    image = img.reshape(1, 3, img_size, img_size).to(device)
    
    with torch.no_grad():
        image_features, patch_features = model.encode_image(image, features_list, DPAM_layer=20)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        
        text_probs = image_features @ text_features.permute(0, 2, 1)
        text_probs = (text_probs/0.07).softmax(-1)
        text_probs = text_probs[:, 0, 1]
        anomaly_score = text_probs.item()
        
        anomaly_map_list = []
        for idx, patch_feature in enumerate(patch_features):
            if idx >= feature_map_layer[0]:
                patch_feature = patch_feature/ patch_feature.norm(dim=-1, keepdim=True)
                similarity, _ = AnomalyCLIP_lib.compute_similarity(patch_feature, text_features[0])
                similarity_map = AnomalyCLIP_lib.get_similarity_map(similarity[:, 1:, :], img_size)
                anomaly_map = (similarity_map[...,1] + 1 - similarity_map[...,0])/2.0
                anomaly_map_list.append(anomaly_map)
        
        anomaly_map = torch.stack(anomaly_map_list)
        anomaly_map = anomaly_map.sum(dim=0)
        anomaly_map = torch.stack([torch.from_numpy(gaussian_filter(i, sigma=sigma)) for i in anomaly_map.detach().cpu()], dim=0)
    
    if os.path.exists(preprocessed_path):
        os.remove(preprocessed_path)
    
    return anomaly_score, anomaly_map

# 生成异常热力图
def generate_heatmap(image_path, anomaly_map):
    img_size = 518
    vis = cv2.cvtColor(cv2.resize(cv2.imread(image_path), (img_size, img_size)), cv2.COLOR_BGR2RGB)
    mask = normalize(anomaly_map[0])
    if torch.is_tensor(mask):
        mask = mask.detach().cpu().numpy()
    np_image = np.asarray(vis, dtype=float)
    scoremap = (mask * 255).astype(np.uint8)
    scoremap = cv2.applyColorMap(scoremap, cv2.COLORMAP_JET)
    scoremap = cv2.cvtColor(scoremap, cv2.COLOR_BGR2RGB)
    heatmap = (0.5 * np_image + 0.5 * scoremap).astype(np.uint8)
    heatmap = cv2.cvtColor(heatmap, cv2.COLOR_RGB2BGR)
    
    _, buffer = cv2.imencode('.png', heatmap)
    img_str = base64.b64encode(buffer).decode('utf-8')
    return img_str

@app.route('/api/detect', methods=['POST'])
def detect():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    upload_dir = './uploads'
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    timestamp = int(time.time())
    filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(upload_dir, filename)
    file.save(file_path)
    
    threshold = float(request.form.get('threshold', 0.6))
    material = request.form.get('material', 'cotton')
    precision = request.form.get('precision', 'precision')
    
    try:
        img = cv2.imread(file_path)
        height, width = img.shape[:2]
        if min(height, width) < 200:
            return jsonify({'error': '图像分辨率过低，无法保证检测精度≥2mm'}), 400
        
        anomaly_score, anomaly_map = detect_anomaly(file_path, material, precision)
        heatmap_base64 = generate_heatmap(file_path, anomaly_map)
        
        os.remove(file_path)
        
        return jsonify({
            'anomaly_score': anomaly_score,
            'heatmap': heatmap_base64,
            'is_anomalous': anomaly_score > threshold
        })
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
