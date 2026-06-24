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
import qrcode
import base64
import tempfile
import atexit

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
TARGET_PHONE = '41998239031'

# Inicializar WhatsApp
whatsapp_initialized = False

# Dados em memória
gastos = []
scheduler = None

# Flag para controlar se estamos no Render
IS_RENDER = os.environ.get('RENDER', False)

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

def send_whatsapp_message_web(message):
    """Envia mensagem via WhatsApp Web usando a interface web"""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
        import time
        
        logger.info("Enviando mensagem via WhatsApp Web...")
        
        chrome_options = Options()
        
        # Configurações para ambiente sem interface gráfica
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1280,720')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Iniciar driver
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Acessar WhatsApp Web
        driver.get('https://web.whatsapp.com')
        
        # Tentar carregar sessão
        if os.path.exists('whatsapp_session.json'):
            try:
                with open('whatsapp_session.json', 'r') as f:
                    cookies = json.load(f)
                for cookie in cookies:
                    driver.add_cookie(cookie)
                driver.refresh()
            except:
                logger.warning("Erro ao carregar sessão, continuando...")
        
        # Aguardar carregar
        wait = WebDriverWait(driver, 60)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='chat-list']")))
        
        # Abrir chat com o número
        phone = TARGET_PHONE
        if not phone.startswith('55'):
            phone = f'55{phone}'
        
        # Limpar número para URL
        phone_clean = ''.join(filter(str.isdigit, phone))
        driver.get(f'https://web.whatsapp.com/send?phone={phone_clean}')
        
        # Aguardar carregar
        time.sleep(3)
        
        # Encontrar campo de mensagem
        input_box = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[contenteditable='true']"))
        )
        
        # Digitar mensagem
        input_box.click()
        input_box.clear()
        input_box.send_keys(message)
        time.sleep(1)
        
        # Clicar no botão enviar
        send_button = driver.find_element(By.CSS_SELECTOR, "button[data-testid='compose-btn-send']")
        send_button.click()
        
        logger.info(f"Mensagem enviada com sucesso!")
        
        # Salvar sessão
        try:
            cookies = driver.get_cookies()
            with open('whatsapp_session.json', 'w') as f:
                json.dump(cookies, f)
        except:
            pass
        
        driver.quit()
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
        
        messages_sent = 0
        
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
                success = send_whatsapp_message_web(message)
                if success:
                    messages_sent += 1
                time.sleep(3)  # Pausa entre mensagens
        
        logger.info(f"Total de mensagens enviadas: {messages_sent}")
            
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
    try:
        return send_from_directory('.', 'index.html')
    except:
        return "Sistema de Lembretes Financeiros - API Rodando", 200

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

@app.route('/api/gastos/<gasto_id>/pagar', methods=['POST'])
def marcar_pago(gasto_id):
    """Marca um gasto como pago"""
    try:
        for gasto in gastos:
            if str(gasto.get('id')) == str(gasto_id):
                gasto['pago'] = True
                save_gastos()
                return jsonify({'status': 'success'})
        return jsonify({'error': 'Gasto não encontrado'}), 404
    except Exception as e:
        logger.error(f"Erro ao marcar como pago: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/gastos/<gasto_id>/nao-pago', methods=['POST'])
def marcar_nao_pago(gasto_id):
    """Marca um gasto como não pago"""
    try:
        for gasto in gastos:
            if str(gasto.get('id')) == str(gasto_id):
                gasto['pago'] = False
                save_gastos()
                return jsonify({'status': 'success'})
        return jsonify({'error': 'Gasto não encontrado'}), 404
    except Exception as e:
        logger.error(f"Erro ao marcar como não pago: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/whatsapp/status', methods=['GET'])
def get_whatsapp_status():
    """Retorna status do WhatsApp"""
    return jsonify({
        'connected': os.path.exists('whatsapp_session.json'),
        'session_exists': os.path.exists('whatsapp_session.json')
    })

@app.route('/api/whatsapp/connect', methods=['POST'])
def connect_whatsapp():
    """Conecta ao WhatsApp e retorna QR Code"""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
        import time
        
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.get('https://web.whatsapp.com')
        
        # Aguardar QR Code carregar
        time.sleep(5)
        
        # Capturar QR Code
        qr_element = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='qrcode']"))
        )
        
        qr_data = qr_element.get_attribute('data-ref')
        if qr_data:
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            # Converter para base64
            import io
            img = qr.make_image(fill_color="black", back_color="white")
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            driver.quit()
            return jsonify({
                'qrcode': img_base64,
                'message': 'Escaneie o QR Code com o WhatsApp'
            })
        
        driver.quit()
        return jsonify({'error': 'Não foi possível gerar QR Code'}), 500
        
    except Exception as e:
        logger.error(f"Erro ao conectar WhatsApp: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/whatsapp/test', methods=['POST'])
def test_whatsapp():
    """Testa envio de mensagem"""
    try:
        data = request.json
        message = data.get('message', 'Teste de mensagem do sistema')
        success = send_whatsapp_message_web(message)
        return jsonify({
            'success': success,
            'message': 'Mensagem enviada' if success else 'Erro ao enviar'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def init_scheduler():
    """Inicializa o agendador"""
    global scheduler
    try:
        scheduler = BackgroundScheduler()
        scheduler.add_job(scheduled_job, 'cron', hour=8, minute=0)
        scheduler.start()
        logger.info("Agendador iniciado - Verificações às 08:00")
        return True
    except Exception as e:
        logger.error(f"Erro ao iniciar agendador: {e}")
        return False

def start_app():
    """Inicializa a aplicação"""
    logger.info("Iniciando aplicação...")
    load_gastos()
    init_scheduler()
    
    # Verificar vencimentos na inicialização (apenas se não estiver no Render ou em modo de desenvolvimento)
    if not IS_RENDER:
        logger.info("Executando verificação inicial...")
        # Aguardar um pouco para garantir que tudo está pronto
        time.sleep(2)
        # Executar em uma thread separada para não bloquear
        thread = threading.Thread(target=check_payments)
        thread.daemon = True
        thread.start()
    else:
        logger.info("Pulando verificação inicial no Render - será feita às 08:00")

# Iniciar aplicação
if __name__ == '__main__':
    start_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
else:
    # Para o gunicorn (Render)
    start_app()
