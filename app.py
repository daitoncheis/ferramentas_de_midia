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
import platform # Adicionado para detetar o sistema operativo
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

# AJUSTE DINÂMICO DO IMAGEMAGICK (Windows vs Linux/Nuvem)
if platform.system() == "Windows":
    caminho_imagemagick = r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
    change_settings({"IMAGEMAGICK_BINARY": caminho_imagemagick})
    caminho_fonte = r"C:\Windows\Fonts\arialbd.ttf"
else:
    # No Streamlit Cloud, o binário é detetado automaticamente no PATH
    caminho_fonte = None 

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
if "historico_producao" not in st.session_state:
    st.session_state.historico_producao = []

abas_nomes = ["🎥 Fábrica", "🛠️ VEO 3", "🖼️ Coleções", "🎬 CapCut", "📂 Extrair Mídia"]
for aba in abas_nomes:
    if f"log_{aba}" not in st.session_state:
        st.session_state[f"log_{aba}"] = f"Log de {aba} iniciado.\n"

if "gerando_infinito" not in st.session_state: st.session_state.gerando_infinito = False
if "colecao_paths" not in st.session_state: st.session_state.colecao_paths = []
if "temp_imgs" not in st.session_state: st.session_state.temp_imgs = []
if "prompt_temp" not in st.session_state: st.session_state.prompt_temp = ""

def registrar_producao(nome_arquivo, tipo):
    hora = datetime.datetime.now().strftime("%H:%M:%S")
    st.session_state.historico_producao.insert(0, {
        "hora": hora, 
        "arquivo": nome_arquivo, 
        "tipo": tipo
    })

# --- FUNÇÕES AUXILIARES ---
def adicionar_log(msg, aba_atual):
    hora = datetime.datetime.now().strftime("%H:%M:%S")
    st.session_state[f"log_{aba_atual}"] += f"[{hora}] {msg}\n"

@st.cache_resource
def carregar_whisper(): return whisper.load_model("base")

def listar_arquivos(pasta, ext):
    return sorted([f for f in os.listdir(pasta) if f.endswith(ext)])

def criar_zip(lista):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in lista:
            if os.path.exists(f): zf.write(f, arcname=os.path.basename(f))
    return buf.getvalue()

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

# --- SIDEBAR (HISTÓRICO) ---
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

# --- ABA 1: FÁBRICA ---
if escolha_aba == "🎥 Fábrica":
    st.header("🎥 Fábrica de Vídeos Automática")
    url_v = st.text_input("🔗 Link do vídeo original:")
    voz_v = st.selectbox("🎙️ Voz IA:", ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"])
    
    col_f1, col_f2 = st.columns(2)
    btn_start = col_f1.button("🚀 INICIAR PROCESSO", use_container_width=True, type="primary")
    
    if os.path.exists(os.path.join(PASTA_SAIDA, 'original.mp3')):
        if col_f2.button("💾 SALVAR ÁUDIO NA BIBLIOTECA", use_container_width=True):
            novo_n = f"Extraido_{datetime.datetime.now().strftime('%H%M%S')}.mp3"
            shutil.copy(os.path.join(PASTA_SAIDA, 'original.mp3'), os.path.join(PASTA_SONS, novo_n))
            st.success(f"Salvo: {novo_n}")

    if btn_start and url_v:
        try:
            st.session_state.temp_imgs = []
            with st.status("🛠️ Processando...") as status:
                tmp = os.path.join(PASTA_SAIDA, 'original.mp3')
                ydl_opts = {'format': 'bestaudio/best', 'outtmpl': tmp.replace('.mp3', ''), 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}], 'quiet': True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url_v])
                texto = carregar_whisper().transcribe(tmp)['text']
                
                api_key = os.getenv("GEMINI_API_KEY").strip()
                url_g = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={api_key}"
                prompt_g = f"Aja como robô. Roteiro de 30s e 8 prompts. TEXTO: {texto}\nFORMATO: Roteiro ; P1 ; P2 ; P3 ; P4 ; P5 ; P6 ; P7 ; P8"
                res_g = requests.post(url_g.strip(), json={"contents": [{"parts": [{"text": prompt_g}]}]})
                partes = res_g.json()['candidates'][0]['content']['parts'][0]['text'].replace("```", "").strip().split(";")
                
                c_voz = os.path.join(PASTA_SAIDA, "voz.mp3")
                async def falar(): await edge_tts.Communicate(re.sub(r'[;*#_]', '', partes[0]), voz_v).save(c_voz)
                asyncio.run(falar())

                mod_img = ImageGenerationModel.from_pretrained("imagen-3.0-generate-001")
                for i, p_img in enumerate(partes[1:9]):
                    time.sleep(25)
                    try:
                        ri = mod_img.generate_images(prompt=p_img.strip(), number_of_images=1, aspect_ratio="9:16")
                        path_i = os.path.join(PASTA_SAIDA, f"f_{i}.png")
                        ri[0].save(location=path_i, include_generation_parameters=False)
                        st.session_state.temp_imgs.append(path_i)
                    except: pass

                audio = AudioFileClip(c_voz)
                dur_m = audio.duration / len(st.session_state.temp_imgs)
                clips_m = [ImageClip(p).set_duration(dur_m).resize(height=1920) for p in st.session_state.temp_imgs]
                leg_m = TextClip(txt=partes[0].strip(), font=caminho_fonte, fontsize=55, color="white", method="caption", size=(900, 1600))
                vid_m = CompositeVideoClip([concatenate_videoclips(clips_m, method="compose"), leg_m.set_duration(audio.duration).set_position("center")]).set_audio(audio)
                final_path = os.path.join(PASTA_SAIDA, "final.mp4")
                vid_m.write_videofile(final_path, fps=24, codec="libx264")
                st.video(final_path)
                registrar_producao("final.mp4", "Fábrica Automática")
                status.update(label="✅ Pronto!", state="complete")
                st.balloons()
        except Exception as e: st.error(f"Erro: {e}")

# --- ABA 4: CAPCUT (CORRIGIDA) ---
elif escolha_aba == "🎬 CapCut":
    st.header("🎬 Editor Estilo CapCut")
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        fotos = st.file_uploader("📸 Importar Fotos:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
        som_lib = st.selectbox("🎙️ Som da Biblioteca:", ["Nenhum"] + listar_arquivos(PASTA_SONS, ".mp3"))
        musica_manual = st.file_uploader("📂 Upload Manual Áudio:", type=['mp3'])
    with col_u2:
        modelo = st.selectbox("🎯 Escolha o Estilo:", list(MODELOS_EDICAO.keys()))
        cfg = MODELOS_EDICAO[modelo]
        modo_tempo = st.radio("⏱️ Modo de Troca:", ["Manual", "Batida da Música (Beat Sync)"])
        vel_manual = st.slider("Velocidade (seg):", 0.1, 5.0, 1.5) if modo_tempo == "Manual" else 1.0
        texto_cap = st.text_input("📝 Legenda:", "Dayton Preview")

    if st.button("🚀 RENDER FINAL (HQ)", use_container_width=True, type="primary") and fotos:
        try:
            with st.status("🎬 Editando...") as status:
                c_audio = None
                if musica_manual:
                    c_audio = os.path.join(PASTA_UPLOADS, "t_audio.mp3")
                    with open(c_audio, "wb") as f: f.write(musica_manual.getbuffer())
                elif som_lib != "Nenhum":
                    c_audio = os.path.join(PASTA_SONS, som_lib)

                beat_times = []
                if c_audio and modo_tempo == "Batida da Música (Beat Sync)":
                    y, sr = librosa.load(c_audio)
                    _, b_frames = librosa.beat.beat_track(y=y, sr=sr)
                    beat_times = librosa.frames_to_time(b_frames, sr=sr)

                lista_c = []
                for i, f_up in enumerate(fotos):
                    dur = beat_times[i+1]-beat_times[i] if (modo_tempo == "Batida da Música (Beat Sync)" and i < len(beat_times)-1) else vel_manual
                    path = os.path.join(PASTA_UPLOADS, f"u_{i}.png")
                    with open(path, "wb") as out: out.write(f_up.getbuffer())
                    c = ImageClip(path).set_duration(dur).resize(height=1920)
                    c = aplicar_estilo_visual(c, cfg['cor'])
                    m = cfg['zoom']
                    if m == "alternado": m = "in" if i % 2 == 0 else "out"
                    c = aplicar_zoom_dinamico(c, dur, m)
                    lista_c.append(c)
                
                video = concatenate_videoclips(lista_c, method="compose")
                if c_audio: video = video.set_audio(AudioFileClip(c_audio).set_duration(video.duration))
                
                if texto_cap:
                    leg = TextClip(txt=texto_cap, font=caminho_fonte, fontsize=cfg['fontsize'], color=cfg['texto_cor'], stroke_color="black", stroke_width=1, method="caption", size=(800, 400))
                    video = CompositeVideoClip([video, leg.set_duration(video.duration).set_position(("center", 1400))])

                # CORREÇÃO DA VARIÁVEL DE HISTÓRICO
                out_name = f"final_{int(time.time())}.mp4"
                out_p = os.path.join(PASTA_SAIDA, out_name)
                video.write_videofile(out_p, fps=24, codec="libx264")
                registrar_producao(out_name, f"CapCut: {modelo}")
                
                status.update(label="✅ CONCLUÍDO!", state="complete")
                st.video(out_p)
                st.balloons()
        except Exception as e: st.error(f"Erro: {e}")

# --- ABA 5: EXTRAÇÃO DE MÍDIA (CORRIGIDA) ---
elif escolha_aba == "📂 Extrair Mídia":
    st.header("📂 Extrair Mídia para Biblioteca")
    col_ex1, col_ex2 = st.columns(2)
    with col_ex1:
        st.subheader("📥 Nova Extração")
        url_m = st.text_input("🔗 Link YT/TikTok:")
        nome_m = st.text_input("🏷️ Nome para Salvar:")
        tipo_m = st.radio("📦 Tipo:", ["Áudio (MP3)", "Vídeo Mudo (MP4)"])
        
        if st.button("🚀 EXECUTAR EXTRAÇÃO", type="primary"):
            if url_m and nome_m:
                with st.spinner("Baixando..."):
                    base_p = PASTA_SONS if tipo_m == "Áudio (MP3)" else PASTA_VIDEOS_LIB
                    ext = ".mp3" if tipo_m == "Áudio (MP3)" else ".mp4"
                    n_final = f"{nome_m}{ext}"
                    count = 1
                    while os.path.exists(os.path.join(base_p, n_final)):
                        n_final = f"{nome_m} ({count}){ext}"
                        count += 1
                    
                    c_f = os.path.join(base_p, n_final)
                    
                    # OPÇÕES COM CORREÇÃO PARA COMPATIBILIDADE E CAMUFLAGEM
                    opts = {
                        'impersonate': 'chrome', # Disfarce para evitar bloqueios
                        'quiet': True
                    }
                    
                    if tipo_m == "Áudio (MP3)":
                        opts.update({
                            'format': 'bestaudio/best',
                            'outtmpl': c_f.replace('.mp3', ''),
                            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]
                        })
                    else:
                        # FORÇA O FORMATO MP4 PARA EXIBIÇÃO CORRETA NA NUVEM
                        opts.update({
                            'format': 'bestvideo[ext=mp4]/best[ext=mp4]/best', 
                            'outtmpl': c_f.replace('.mp4', ''), 
                            'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}], 
                            'postprocessor_args': ['-an'] # Remove o som
                        })

                    try:
                        with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url_m])
                        st.success(f"Salvo: {n_final}")
                        registrar_producao(n_final, f"Extração: {tipo_m}")
                        st.rerun()
                    except Exception as e: st.error(f"Erro: {e}")

    with col_ex2:
        st.subheader("📚 Biblioteca")
        lib_e = st.selectbox("Ver:", ["🎵 Áudios", "🎬 Vídeos Mudos"])
        p_alvo = PASTA_SONS if lib_e == "🎵 Áudios" else PASTA_VIDEOS_LIB
        ex_alvo = ".mp3" if lib_e == "🎵 Áudios" else ".mp4"
        
        arqs = listar_arquivos(p_alvo, ex_alvo)
        for a in arqs:
            with st.expander(f"📄 {a}"):
                if ex_alvo == ".mp3": st.audio(os.path.join(p_alvo, a))
                else: st.video(os.path.join(p_alvo, a))
                if st.button(f"🗑️ Excluir {a}", key=f"del_{a}"):
                    os.remove(os.path.join(p_alvo, a))
                    st.rerun()

# --- ABA 3: COLEÇÕES ---
elif escolha_aba == "🖼️ Coleções":
    st.header("🖼️ Gerador de Coleções")
    c1, c2, _ = st.columns([1,1,2])
    if c1.button("✨ Estilo Mineiro"): 
        st.session_state.prompt_temp = "Jovem fofo mineiro, cyberpunk, 8k."
        st.rerun()
    if c2.button("💡 Ideia Aleatória"):
        st.session_state.prompt_temp = "Futuristic samurai Tokyo, 8k."
        st.rerun()

    p_in = st.text_area("Comando:", value=st.session_state.prompt_temp)
    limite = st.number_input("Máximo:", value=10)
    
    if not st.session_state.gerando_infinito:
        if st.button("▶️ INICIAR GERAÇÃO", type="primary"):
            st.session_state.gerando_infinito = True
            st.rerun()
    else:
        if st.button("🛑 PARAR AGORA"):
            st.session_state.gerando_infinito = False
            st.rerun()

    if len(st.session_state.colecao_paths) > 0:
        st.download_button("💾 Baixar ZIP", criar_zip(st.session_state.colecao_paths), "colecao.zip")

    if st.session_state.gerando_infinito:
        mod_inf = ImageGenerationModel.from_pretrained("imagen-3.0-generate-001")
        while st.session_state.gerando_infinito and len(st.session_state.colecao_paths) < limite:
            time.sleep(25)
            salt = ''.join(random.choices(string.ascii_uppercase, k=4))
            try:
                res = mod_inf.generate_images(prompt=f"{p_in} --seed {salt}", number_of_images=1, aspect_ratio="9:16")
                path = os.path.join(PASTA_COLECOES, f"img_{salt}.png")
                res[0].save(location=path, include_generation_parameters=False)
                st.session_state.colecao_paths.append(path)
                st.image(path, width=300)
            except: pass
            if not st.session_state.gerando_infinito: break