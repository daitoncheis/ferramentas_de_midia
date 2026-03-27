import streamlit as st
import librosa
import yt_dlp
import whisper
import os
import datetime
import requests
import json
import asyncio
import edge_tts
import time
import re
import zipfile
import random
import string
import numpy as np
import shutil
import platform # Necessário para detectar Windows/Linux
from io import BytesIO
from dotenv import load_dotenv

# --- VERTEX AI & MOVIEPY ---
import vertexai
from vertexai.preview.vision_models import ImageGenerationModel
from moviepy.editor import TextClip, ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
from moviepy.config import change_settings
import moviepy.video.fx.all as vfx_all
import PIL.Image

if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

# --- 1. CONFIGURAÇÕES ---
load_dotenv()
PASTA_SAIDA = "debug_videos"
PASTA_COLECOES = "colecoes_ia"
PASTA_UPLOADS = "meus_uploads"
PASTA_SONS = "tiktok_sounds"
PASTA_VIDEOS_LIB = "biblioteca_videos"

if os.path.exists("google_creds.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_creds.json"

# AJUSTE INTELIGENTE DO IMAGEMAGICK (Windows vs Nuvem/Linux)
if platform.system() == "Windows":
    caminho_imagemagick = r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
    change_settings({"IMAGEMAGICK_BINARY": caminho_imagemagick})
    caminho_fonte = r"C:\Windows\Fonts\arialbd.ttf"
else:
    caminho_fonte = None # O Streamlit Cloud detecta automaticamente

for p in [PASTA_SAIDA, PASTA_COLECOES, PASTA_UPLOADS, PASTA_SONS, PASTA_VIDEOS_LIB]:
    if not os.path.exists(p): os.makedirs(p)

PROJECT_ID = "gerador-ia-491501" 
LOCATION = "us-central1" 
vertexai.init(project=PROJECT_ID, location=LOCATION)

# --- MODELOS DE EDIÇÃO ---
MODELOS_EDICAO = {
    "🎥 Cinematográfico": {"duracao": 4.5, "zoom": "out", "cor": "frio", "fontsize": 50, "texto_cor": "white"},
    "⚡ TikTok/Fast": {"duracao": 0.8, "zoom": "alternado", "cor": "vibrante", "fontsize": 80, "texto_cor": "yellow"},
    "🎞️ Vintage": {"duracao": 3.0, "zoom": "in", "cor": "sepia", "fontsize": 60, "texto_cor": "antiquewhite"},
    "🔥 Impacto": {"duracao": 1.5, "zoom": "in", "cor": "quente", "fontsize": 70, "texto_cor": "red"}
}

# --- ESTADOS DE SESSÃO ---
abas_nomes = ["🎥 Fábrica", "🛠️ VEO 3", "🖼️ Coleções", "🎬 CapCut", "📂 Extrair Mídia"]
for aba in abas_nomes:
    if f"log_{aba}" not in st.session_state:
        st.session_state[f"log_{aba}"] = f"Log de {aba} iniciado.\n"

if "historico_producao" not in st.session_state:
    st.session_state.historico_producao = []

# --- FUNÇÕES AUXILIARES ---
def registrar_producao(nome_arquivo, tipo):
    hora = datetime.datetime.now().strftime("%H:%M:%S")
    st.session_state.historico_producao.insert(0, {"hora": hora, "arquivo": nome_arquivo, "tipo": tipo})

@st.cache_resource
def carregar_whisper(): return whisper.load_model("base")

def listar_arquivos(pasta, ext):
    return sorted([f for f in os.listdir(pasta) if f.endswith(ext)])

def aplicar_estilo_visual(clip, estilo):
    try:
        if estilo == "frio": return clip.fx(vfx_all.colorx, 0.9).fx(vfx_all.lum_contrast, 0, 10, 128)
        if estilo == "sepia": return clip.fx(vfx_all.blackwhite).fx(vfx_all.colorx, 0.8)
        if estilo == "vibrante": return clip.fx(vfx_all.colorx, 1.3)
        if estilo == "quente": return clip.fx(vfx_all.colorx, 1.1)
    except: pass
    return clip

def aplicar_zoom_dinamico(clip, duracao, modo='in'):
    if modo == 'in': return clip.resize(lambda t: 1 + 0.05 * t).set_duration(duracao)
    return clip.resize(lambda t: 1.15 - 0.05 * t).set_duration(duracao)

# --- 2. INTERFACE ---
st.set_page_config(page_title="G - IA Video Factory v8.5", layout="wide")
escolha_aba = st.radio("Navegação", abas_nomes, horizontal=True, label_visibility="collapsed")

st.sidebar.title(f"📊 Painel de Controle")
st.sidebar.markdown("### 🕒 Histórico de Downloads")
if st.session_state.historico_producao:
    for item in st.session_state.historico_producao:
        with st.sidebar.expander(f"✅ {item['hora']} - {item['tipo']}"):
            st.write(f"📄 {item['arquivo']}")
    if st.sidebar.button("🗑️ Limpar Histórico"):
        st.session_state.historico_producao = []
        st.rerun()
else:
    st.sidebar.info("Nenhum vídeo gerado.")

st.sidebar.divider()
st.sidebar.code(st.session_state[f"log_{escolha_aba}"])

# --- ABA 4: CAPCUT (CORRIGIDA) ---
if escolha_aba == "🎬 CapCut":
    st.header("🎬 Editor Estilo CapCut")
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        fotos = st.file_uploader("📸 Fotos:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
        som_lib = st.selectbox("🎙️ Som Biblioteca:", ["Nenhum"] + listar_arquivos(PASTA_SONS, ".mp3"))
        musica_manual = st.file_uploader("📂 Upload Áudio:", type=['mp3'])
    with col_u2:
        modelo = st.selectbox("🎯 Estilo:", list(MODELOS_EDICAO.keys()))
        cfg = MODELOS_EDICAO[modelo]
        modo_tempo = st.radio("⏱️ Troca:", ["Manual", "Beat Sync"])
        vel_manual = st.slider("Segundos:", 0.1, 5.0, 1.5) if modo_tempo == "Manual" else 1.0
        texto_cap = st.text_input("📝 Legenda:", "Dayton Preview")

    if st.button("🚀 RENDER FINAL", use_container_width=True, type="primary") and fotos:
        try:
            with st.status("🎬 Editando...") as status:
                c_audio = None
                if musica_manual:
                    c_audio = os.path.join(PASTA_UPLOADS, "t_audio.mp3")
                    with open(c_audio, "wb") as f: f.write(musica_manual.getbuffer())
                elif som_lib != "Nenhum":
                    c_audio = os.path.join(PASTA_SONS, som_lib)

                lista_c = []
                for i, f_up in enumerate(fotos):
                    path = os.path.join(PASTA_UPLOADS, f"u_{i}.png")
                    with open(path, "wb") as out: out.write(f_up.getbuffer())
                    c = ImageClip(path).set_duration(vel_manual).resize(height=1920)
                    c = aplicar_estilo_visual(c, cfg['cor'])
                    c = aplicar_zoom_dinamico(c, vel_manual, cfg['zoom'])
                    lista_c.append(c)
                
                video = concatenate_videoclips(lista_c, method="compose")
                if c_audio: video = video.set_audio(AudioFileClip(c_audio).set_duration(video.duration))
                
                out_name = f"final_{int(time.time())}.mp4"
                out_p = os.path.join(PASTA_SAIDA, out_name)
                video.write_videofile(out_p, fps=24, codec="libx264")
                
                registrar_producao(out_name, f"CapCut: {modelo}")
                status.update(label="✅ CONCLUÍDO!", state="complete")
                st.video(out_p)
                st.balloons()
        except Exception as e: st.error(f"Erro: {e}")

# --- ABA 5: EXTRAÇÃO (CORRIGIDA COM CAMUFLAGEM) ---
elif escolha_aba == "📂 Extrair Mídia":
    st.header("📂 Extrair Mídia para Biblioteca")
    url_m = st.text_input("🔗 Link YT/TikTok:")
    nome_m = st.text_input("🏷️ Nome para Salvar:")
    tipo_m = st.radio("📦 Tipo:", ["Áudio (MP3)", "Vídeo Mudo (MP4)"])
    
    if st.button("🚀 EXECUTAR EXTRAÇÃO") and url_m and nome_m:
        with st.spinner("Processando..."):
            base_p = PASTA_SONS if tipo_m == "Áudio (MP3)" else PASTA_VIDEOS_LIB
            ext = ".mp3" if tipo_m == "Áudio (MP3)" else ".mp4"
            n_final = f"{nome_m}{ext}"
            c_f = os.path.join(base_p, n_final)
            
            opts = {
                'impersonate': 'chrome', # Disfarce essencial
                'quiet': True,
                'outtmpl': c_f.replace(ext, '')
            }
            if tipo_m == "Áudio (MP3)":
                opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]})
            else:
                opts.update({'format': 'bestvideo[ext=mp4]/best', 'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}], 'postprocessor_args': ['-an']})

            try:
                with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url_m])
                st.success(f"Salvo: {n_final}")
                registrar_producao(n_final, f"Extração: {tipo_m}")
                st.rerun()
            except Exception as e: st.error(f"Erro: {e}")