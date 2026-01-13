import streamlit as st
import asyncio
import qrcode
from PIL import Image
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import InputMessagesFilterPhotos, InputMessagesFilterVideo, MessageService

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Migrador Telegram Web", page_icon="📲", layout="centered")

# --- ESTILOS CSS PARA QUE SE VEA BIEN ---
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 5px; height: 3em;}
    .success {color: #2e7d32; font-weight: bold;}
    </style>
""", unsafe_allow_html=True)

# --- GESTIÓN DE ESTADO (MEMORIA) ---
if "client" not in st.session_state:
    st.session_state.client = None
if "is_logged_in" not in st.session_state:
    st.session_state.is_logged_in = False
if "chats" not in st.session_state:
    st.session_state.chats = {}

# --- FUNCIONES ---
def generar_imagen_qr(url):
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

async def proceso_login_qr(api_id, api_hash):
    """Maneja la lógica del QR con Telethon"""
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    await client.connect()
    
    if not await client.is_user_authorized():
        # Generamos QR
        qr_login = await client.qr_login()
        
        # Mostramos QR en la Web
        img = generar_imagen_qr(qr_login.url)
        st.session_state.qr_placeholder.image(img, caption="Escanea con Telegram > Ajustes > Dispositivos", width=250)
        st.info("⏳ Tienes unos 30 segundos para escanear...")
        
        # Esperamos el escaneo
        try:
            # wait() bloquea hasta que se escanea
            await qr_login.wait()
            return client
        except Exception as e:
            st.error(f"El QR caducó o hubo un error: {e}")
            return None
    else:
        return client

async def get_chats(client):
    dialogs = await client.get_dialogs(limit=None)
    chat_map = {}
    for d in dialogs:
        # Filtramos para que salgan chats, canales y grupos
        if d.is_group or d.is_channel or d.is_user:
            clean_name = d.name.strip() or "Sin Nombre"
            chat_map[f"{clean_name} (ID: {d.id})"] = d
    return chat_map

async def migrar(client, origen, destino, progress_bar, status_text):
    cnt = 0
    async for message in client.iter_messages(origen, reverse=True):
        # Filtros de seguridad
        if isinstance(message, MessageService): continue # Ignorar mensajes de sistema
        if message.web_preview: continue # Ignorar links con vista previa
        if not (message.photo or message.video): continue # Solo multimedia
        
        try:
            await client.forward_messages(destino, message)
            cnt += 1
            status_text.text(f"🚀 Moviendo archivo #{cnt}...")
        except Exception as e:
            # Si hay FloodWait (espera obligatoria), esperamos y reintentamos una vez
            if "seconds" in str(e):
                import re
                sec = int(re.search(r'\d+', str(e)).group())
                status_text.warning(f"⏳ Telegram pide pausa de {sec}s...")
                await asyncio.sleep(sec)
                await client.forward_messages(destino, message)
                cnt += 1
            else:
                pass
    return cnt

# ================= INTERFAZ DE USUARIO =================

st.title("📲 Migrador Telegram (Cloud)")

# --- FASE 1: LOGIN ---
if not st.session_state.is_logged_in:
    st.markdown("### 1. Iniciar Sesión")
    st.warning("⚠️ Streamlit Cloud es público. Usa esto solo para migraciones puntuales y no compartas la URL mientras lo usas.")
    
    col1, col2 = st.columns(2)
    api_id = col1.text_input("API ID")
    api_hash = col2.text_input("API Hash", type="password")
    
    st.session_state.qr_placeholder = st.empty() # Hueco reservado para el QR
    
    if st.button("Generar Código QR"):
        if not api_id or not api_hash:
            st.error("Faltan credenciales.")
        else:
            # Ejecutamos el loop asíncrono
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            client = loop.run_until_complete(proceso_login_qr(api_id, api_hash))
            
            if client and loop.run_until_complete(client.is_user_authorized()):
                st.session_state.client = client
                st.session_state.is_logged_in = True
                # Descargar chats de una vez
                chats = loop.run_until_complete(get_chats(client))
                st.session_state.chats = chats
                st.rerun() # Recargar página para mostrar Fase 2

# --- FASE 2: PANEL DE CONTROL ---
else:
    st.success("✅ ¡Conectado correctamente!")
    
    # Mostrar StringSession por seguridad (para no tener que escanear siempre)
    with st.expander("🔑 Ver mi 'Llave de Sesión' (Guardar para futuro)", expanded=False):
        client = st.session_state.client
        # Truco para sacar la session string en entorno sync
        session_str = client.session.save()
        st.code(session_str)
        st.caption("Si guardas este código, la próxima vez podrías hacer un login directo sin QR (requiere adaptar el script).")

    st.markdown("### 2. Configurar Migración")
    
    if st.session_state.chats:
        nombres_chats = list(st.session_state.chats.keys())
        
        col_a, col_b = st.columns(2)
        origen_key = col_a.selectbox("📤 Desde (Origen)", nombres_chats)
        destino_key = col_b.selectbox("📥 Hacia (Destino)", nombres_chats)
        
        if st.button("🚀 COMENZAR MIGRACIÓN"):
            if origen_key == destino_key:
                st.error("Origen y Destino no pueden ser iguales.")
            else:
                chat_ori = st.session_state.chats[origen_key]
                chat_dest = st.session_state.chats[destino_key]
                
                st.divider()
                progress = st.progress(0)
                status = st.empty()
                
                # Ejecutar migración
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Reconectar cliente al nuevo loop (necesario en streamlit)
                # Usamos la sesión que ya tenemos en memoria
                client.loop = loop
                if not client.is_connected():
                    loop.run_until_complete(client.connect())

                total_movidos = loop.run_until_complete(migrar(client, chat_ori, chat_dest, progress, status))
                
                status.empty()
                st.balloons()
                st.success(f"🏁 ¡Proceso Terminado! Se movieron {total_movidos} archivos.")
                
    else:
        st.error("No se pudieron cargar los chats. Intenta recargar la página.")