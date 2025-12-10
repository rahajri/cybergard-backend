# scripts/download_camembert.py
from transformers import XLMRobertaTokenizer, XLMRobertaModel
import os

os.environ['HF_HOME'] = './models'

print("Téléchargement de XLM-RoBERTa (multilingue FR/EN)...")
model_name = "xlm-roberta-base"

tokenizer = XLMRobertaTokenizer.from_pretrained(model_name)
model = XLMRobertaModel.from_pretrained(model_name)

print(f"XLM-RoBERTa téléchargé dans : {os.environ.get('HF_HOME')}")
print("Modèle multilingue prêt (FR/EN)")