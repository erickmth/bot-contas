import os
import json
import logging
import datetime
import time
import threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from pywa import WhatsApp
import qrcode
import base64

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.')
CORS(app)

# Configurações
DATA_FILE = 'gastos.json'
WHATSAPP_SESSION = 'whatsapp_session.json'
TARGET_PHONE = '41998239031'  # Número que receberá os lembretes

# Inicializar WhatsApp
whatsapp = None
whatsapp_initialized = False

# Dados em memória
gastos = []
scheduler = None

def load_gastos():
    """Carrega os gastos do arquivo JSON"""
    global gastos
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                gastos = json.load(f)
        else:
            gastos = []
        logger.info(f"Carregados {len(gastos)} gastos do arquivo")
    except Exception as e:
        logger.error(f"Erro ao carregar gastos: {e}")
        gastos = []

def save_gastos():
    """Salva os gastos no arquivo JSON"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(gastos, f, ensure_ascii=False, indent=2)
        logger.info(f"Salvos {len(gastos)} gastos")
    except Exception as e:
        logger.error(f"Erro ao salvar gastos: {e}")

def format_br_date(date_str):
    """Formata data no padrão brasileiro"""
    try:
        if '/' in date_str:
            day, month, year = date_str.split('/')
            if len(year) == 2:
                year = f'20{year}'
            return f"{day}/{month}/{year}"
        return date_str
    except:
        return date_str

def parse_date(date_str):
    """Converte data string para objeto datetime"""
    try:
        if '/' in date_str:
            day, month, year = date_str.split('/')
            if len(year) == 2:
                year = f'20{year}'
            return datetime.datetime(int(year), int(month), int(day))
    except:
        return None
    return None

def calculate_days_until(date_str):
    """Calcula dias até uma data"""
    try:
        target = parse_date(date_str)
        if target:
            today = datetime.datetime.now()
            delta = target - today
            return delta.days
    except:
        pass
    return None

def init_whatsapp():
    """Inicializa o WhatsApp Web"""
    global whatsapp, whatsapp_initialized
    
    try:
        if not os.path.exists('whatsapp_session.json'):
            # Gerar QR Code para login
            logger.info("==========================================")
            logger.info("SCANEIE O QR CODE ABAIXO COM O WHATSAPP")
            logger.info("==========================================")
            
            # Iniciar WhatsApp em modo headless
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            import time
            
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1280,720')
            
            driver = webdriver.Chrome(options=chrome_options)
            driver.get('https://web.whatsapp.com')
            
            # Aguardar QR Code carregar
            time.sleep(5)
            
            # Capturar QR Code e exibir
            qr_element = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='qrcode']"))
            )
            
            qr_data = qr_element.get_attribute('data-ref')
            if qr_data:
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(qr_data)
                qr.make(fit=True)
                
                # Exibir QR Code no terminal
                qr.print_ascii()
                
                # Salvar QR Code em arquivo
                img = qr.make_image(fill_color="black", back_color="white")
                img.save('whatsapp_qrcode.png')
                logger.info("QR Code salvo como 'whatsapp_qrcode.png'")
                
                # Aguardar login
                logger.info("Aguardando login no WhatsApp...")
                WebDriverWait(driver, 120).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='chat-list']"))
                )
                
                # Salvar sessão
                cookies = driver.get_cookies()
                with open('whatsapp_session.json', 'w') as f:
                    json.dump(cookies, f)
                
                logger.info("WhatsApp conectado com sucesso!")
                driver.quit()
                whatsapp_initialized = True
                return True
            
        else:
            # Carregar sessão existente
            logger.info("Carregando sessão do WhatsApp...")
            with open('whatsapp_session.json', 'r') as f:
                cookies = json.load(f)
            
            # Verificar se a sessão ainda é válida
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            
            driver = webdriver.Chrome(options=chrome_options)
            driver.get('https://web.whatsapp.com')
            
            for cookie in cookies:
                driver.add_cookie(cookie)
            
            driver.refresh()
            
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='chat-list']"))
                )
                logger.info("WhatsApp reconectado com sucesso!")
                driver.quit()
                whatsapp_initialized = True
                return True
            except:
                logger.warning("Sessão expirada, necessário novo login")
                os.remove('whatsapp_session.json')
                return init_whatsapp()
                
    except Exception as e:
        logger.error(f"Erro ao inicializar WhatsApp: {e}")
        return False

def send_whatsapp_message(message):
    """Envia mensagem via WhatsApp"""
    global whatsapp_initialized
    
    if not whatsapp_initialized:
        logger.warning("WhatsApp não inicializado, tentando reconectar...")
        if not init_whatsapp():
            return False
    
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        import time
        
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.get('https://web.whatsapp.com')
        
        # Carregar sessão
        with open('whatsapp_session.json', 'r') as f:
            cookies = json.load(f)
        for cookie in cookies:
            driver.add_cookie(cookie)
        driver.refresh()
        
        # Aguardar carregar
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='chat-list']"))
        )
        
        # Abrir chat
        phone = TARGET_PHONE
        if not phone.startswith('55'):
            phone = f'55{phone}'
        
        driver.get(f'https://web.whatsapp.com/send?phone={phone}')
        
        # Aguardar input aparecer
        time.sleep(3)
        
        # Encontrar campo de mensagem
        input_box = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[contenteditable='true']"))
        )
        
        # Digitar e enviar
        input_box.send_keys(message)
        time.sleep(1)
        
        send_button = driver.find_element(By.CSS_SELECTOR, "button[data-testid='compose-btn-send']")
        send_button.click()
        
        time.sleep(2)
        driver.quit()
        
        logger.info(f"Mensagem enviada: {message[:50]}...")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")
        return False

def check_payments():
    """Verifica vencimentos e envia lembretes"""
    global gastos
    
    try:
        today = datetime.datetime.now().date()
        logger.info("Verificando vencimentos...")
        
        for gasto in gastos:
            if gasto.get('pago', False):
                continue
            
            data_pagamento = gasto.get('data_pagamento', '')
            if not data_pagamento:
                continue
            
            days_until = calculate_days_until(data_pagamento)
            if days_until is None:
                continue
            
            message = None
            if days_until == 5:
                message = f"⚠️ Lembrete: A conta {gasto['nome']} vence em 5 dias. Valor: R$ {gasto['valor']}"
            elif days_until == 1:
                message = f"⚠️ Amanhã vence a conta {gasto['nome']}. Valor: R$ {gasto['valor']}"
            elif days_until == 0:
                message = f"🚨 Hoje vence a conta {gasto['nome']}. Valor: R$ {gasto['valor']}"
            
            if message:
                logger.info(f"Enviando lembrete: {message}")
                send_whatsapp_message(message)
                time.sleep(2)  # Pausa entre mensagens
            
    except Exception as e:
        logger.error(f"Erro ao verificar pagamentos: {e}")

def scheduled_job():
    """Job agendado para as 08:00"""
    logger.info("Executando job agendado das 08:00")
    check_payments()

# Rotas da API

@app.route('/')
def index():
    """Serve a página principal"""
    return send_from_directory('.', 'index.html')

@app.route('/api/gastos', methods=['GET'])
def get_gastos():
    """Retorna todos os gastos"""
    return jsonify(gastos)

@app.route('/api/gastos/sync', methods=['POST'])
def sync_gastos():
    """Sincroniza dados da planilha"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Dados não fornecidos'}), 400
        
        novos_gastos = data.get('gastos', [])
        
        # Converter dados
        for gasto in novos_gastos:
            if not gasto.get('id'):
                gasto['id'] = str(int(time.time() * 1000)) + str(len(gastos))
            gasto['pago'] = gasto.get('pago', False)
        
        # Atualizar gastos existentes ou adicionar novos
        for novo_gasto in novos_gastos:
            exists = False
            for i, gasto in enumerate(gastos):
                if gasto.get('nome') == novo_gasto.get('nome') and gasto.get('data_pagamento') == novo_gasto.get('data_pagamento'):
                    gastos[i] = novo_gasto
                    exists = True
                    break
            if not exists:
                gastos.append(novo_gasto)
        
        save_gastos()
        logger.info(f"Sincronizados {len(novos_gastos)} gastos")
        return jsonify({'status': 'success', 'count': len(novos_gastos)})
        
    except Exception as e:
        logger.error(f"Erro ao sincronizar: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/gastos/<int:gasto_id>/pagar', methods=['POST'])
def marcar_pago(gasto_id):
    """Marca um gasto como pago"""
    try:
        for gasto in gastos:
            if gasto.get('id') == str(gasto_id) or gasto.get('id') == gasto_id:
                gasto['pago'] = True
                save_gastos()
                return jsonify({'status': 'success'})
        return jsonify({'error': 'Gasto não encontrado'}), 404
    except Exception as e:
        logger.error(f"Erro ao marcar como pago: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/gastos/<int:gasto_id>/nao-pago', methods=['POST'])
def marcar_nao_pago(gasto_id):
    """Marca um gasto como não pago"""
    try:
        for gasto in gastos:
            if gasto.get('id') == str(gasto_id) or gasto.get('id') == gasto_id:
                gasto['pago'] = False
                save_gastos()
                return jsonify({'status': 'success'})
        return jsonify({'error': 'Gasto não encontrado'}), 404
    except Exception as e:
        logger.error(f"Erro ao marcar como não pago: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/whatsapp/qrcode', methods=['GET'])
def get_qrcode():
    """Retorna o QR Code do WhatsApp"""
    try:
        if os.path.exists('whatsapp_qrcode.png'):
            with open('whatsapp_qrcode.png', 'rb') as f:
                img_data = f.read()
                img_base64 = base64.b64encode(img_data).decode('utf-8')
                return jsonify({'qrcode': img_base64})
        return jsonify({'error': 'QR Code não encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/whatsapp/status', methods=['GET'])
def get_whatsapp_status():
    """Retorna status do WhatsApp"""
    return jsonify({
        'connected': whatsapp_initialized,
        'session_exists': os.path.exists('whatsapp_session.json')
    })

def init_scheduler():
    """Inicializa o agendador"""
    global scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_job, 'cron', hour=8, minute=0)
    scheduler.start()
    logger.info("Agendador iniciado - Verificações às 08:00")

def start_app():
    """Inicializa a aplicação"""
    load_gastos()
    init_scheduler()
    
    # Tentar inicializar WhatsApp
    try:
        init_whatsapp()
    except Exception as e:
        logger.error(f"Erro ao iniciar WhatsApp: {e}")
    
    # Verificar vencimentos na inicialização
    check_payments()

if __name__ == '__main__':
    # Iniciar aplicação
    start_app()
    
    # Executar em modo debug
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
