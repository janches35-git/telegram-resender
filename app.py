import streamlit as st
import asyncio
import qrcode
import io
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import InputMessagesFilterPhotos, InputMessagesFilterVideo, MessageService
from telethon.errors import ApiIdInvalidError, SessionPasswordNeededError

# --- CONFIGURACIÓN VISUAL ---
st.set_page_config(page_title="Migrador Telegram Pro", page_icon="✈️", layout="wide")

# CSS para imitar la consola negra
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 5px; font-weight: bold;}
    .log-box {
        background-color: #0e1117;
        color: #00ff00;
        font-family: 'Courier New', Courier, monospace;
        padding: 15px;
        border-radius: 5px;
        height: 500px;
        overflow-y: scroll;
        border: 1px solid #333;
        font-size: 12px;
        white-space: pre-wrap;
    }
    </style>
""", unsafe_allow_html=True)

# --- INICIALIZACIÓN DE ESTADO (AQUÍ ESTABA EL ERROR) ---
# Definimos TODAS las variables al principio para evitar AttributeError
if "client" not in st.session_state: 
    st.session_state.client = None
if "chats" not in st.session_state: 
    st.session_state.chats = {}
if "logs" not in st.session_state: 
    st.session_state.logs = ["--- SISTEMA LISTO ---"]
if "is_logged_in" not in st.session_state: 
    st.session_state.is_logged_in = False

# --- FUNCIONES ---
def add_log(texto):
    """Añade texto a la consola virtual"""
    st.session_state.logs.append(f">> {texto}")

def get_qr_image(url):
    """Genera el QR y lo convierte a BYTES"""
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img_pil = qr.make_image(fill_color="black", back_color="white")
    
    img_byte_arr = io.BytesIO()
    img_pil.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

async def login_process(api_id, api_hash):
    """Proceso de login robusto"""
    try:
        client = TelegramClient(StringSession(), int(api_id), api_hash)
        await client.connect()
    except Exception as e:
        return None, f"Error de conexión inicial: {e}"

    if not await client.is_user_authorized():
        try:
            qr_login = await client.qr_login()
            return client, qr_login
        except ApiIdInvalidError:
            return None, "❌ ERROR CRÍTICO: El API ID o el HASH son incorrectos."
        except Exception as e:
            return None, f"Error generando QR: {e}"
    
    return client, "AUTHORIZED"

async def fetch_chats(client):
    dialogs = await client.get_dialogs(limit=None)
    chat_map = {}
    for d in dialogs:
        if d.is_group or d.is_channel or d.is_user:
            icono = "👥" if d.is_group else ("📢" if d.is_channel else "👤")
            name = d.name.strip() or "Sin Nombre"
            label = f"{icono} {name}"
            chat_map[f"{label} (ID: {d.id})"] = d
    return chat_map

async def run_migration(client, ori, dest, status_slot):
    cnt = 0
    try:
        async for msg in client.iter_messages(ori, reverse=True):
            if isinstance(msg, MessageService) or msg.web_preview: continue
            if not (msg.photo or msg.video): continue

            try:
                await client.forward_messages(dest, msg)
                cnt += 1
                if cnt % 5 == 0:
                    status_slot.text(f"🚀 Moviendo archivo #{cnt}...")
            except Exception as e:
                if "seconds" in str(e):
                    import re
                    try:
                        sec = int(re.search(r'\d+', str(e)).group())
                    except: sec = 10
                    status_slot.warning(f"⏳ Pausa obligatoria de {sec}s...")
                    await asyncio.sleep(sec)
                    await client.forward_messages(dest, msg)
                    cnt += 1
    except Exception as e:
        status_slot.error(f"Error en bucle: {e}")
    
    return cnt

# ================= LAYOUT PRINCIPAL =================
col_izq, col_der = st.columns([1, 1])

# --- DERECHA (LOG) ---
with col_der:
    st.markdown("### 📝 Registro de Actividad")
    # Mostrar logs en orden inverso (nuevos abajo)
    log_content = "\n".join(st.session_state.logs)
    st.markdown(f'<div class="log-box">{log_content}</div>', unsafe_allow_html=True)

# --- IZQUIERDA (CONTROLES) ---
with col_izq:
    st.title("✨ Migrador Telegram")
    
    # CREDENCIALES
    with st.expander("🔑 Credenciales", expanded=not st.session_state.is_logged_in):
        api_id = st.text_input("API ID")
        api_hash = st.text_input("API Hash", type="password")

    # BOTÓN CONEXIÓN (Si NO estamos logueados)
    if not st.session_state.is_logged_in:
        if st.button("🔌 CONECTAR Y GENERAR QR", type="primary"):
            if not api_id or not api_hash:
                st.error("Faltan datos.")
            else:
                add_log("Iniciando conexión...")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    client_temp, result = loop.run_until_complete(login_process(api_id, api_hash))
                    
                    if client_temp is None:
                        st.error(result)
                        add_log(result)
                    elif result == "AUTHORIZED":
                        st.session_state.client = client_temp
                        st.session_state.is_logged_in = True
                        add_log("✅ Conexión directa exitosa.")
                        chats = loop.run_until_complete(fetch_chats(client_temp))
                        st.session_state.chats = chats
                        st.rerun()
                    else:
                        # QR LOGIN
                        qr_login_obj = result
                        st.session_state.client = client_temp
                        
                        img_bytes = get_qr_image(qr_login_obj.url)
                        
                        st.image(img_bytes, width=250, caption="ESCANEA RÁPIDO")
                        st.info("⏳ Esperando escaneo...")
                        add_log("QR Generado. Esperando usuario...")
                        
                        try:
                            # Esperar escaneo
                            loop.run_until_complete(qr_login_obj.wait())
                            
                            st.session_state.is_logged_in = True
                            add_log("✅ ¡Login QR Exitoso!")
                            st.success("Logueado. Recargando...")
                            
                            chats = loop.run_until_complete(fetch_chats(client_temp))
                            st.session_state.chats = chats
                            st.rerun()
                        except Exception as e:
                            st.error(f"El QR caducó o falló: {e}")
                            add_log("❌ Error QR: Caducado o fallo.")

                except Exception as e:
                    st.error(f"Error inesperado: {e}")
                    add_log(f"Error CRITICO: {e}")

    # SELECTORES (Si SÍ estamos logueados)
    if st.session_state.is_logged_in:
        st.success("✅ CONECTADO")
        
        if st.session_state.chats:
            opciones = list(st.session_state.chats.keys())
            
            st.write("---")
            col_ori, col_dest = st.columns(2)
            with col_ori:
                origen = st.selectbox("📤 Origen", opciones)
            with col_dest:
                destino = st.selectbox("📥 Destino", opciones)
                
            if st.button("🚀 INICIAR MIGRACIÓN", type="primary"):
                if origen == destino:
                    st.error("Origen y destino son iguales")
                    add_log("❌ Error: Origen == Destino")
                else:
                    add_log(f"Iniciando: {origen} -> {destino}")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    client = st.session_state.client
                    client.loop = loop
                    if not client.is_connected():
                        loop.run_until_complete(client.connect())
                    
                    chat_o = st.session_state.chats[origen]
                    chat_d = st.session_state.chats[destino]
                    
                    status_text = st.empty()
                    
                    total = loop.run_until_complete(run_migration(client, chat_o, chat_d, status_text))
                    
                    st.balloons()
                    add_log(f"🏁 FIN. Total archivos: {total}")
                    st.success(f"Migración completada. {total} archivos.")
        else:
            st.warning("No se encontraron chats o la sesión expiró.")