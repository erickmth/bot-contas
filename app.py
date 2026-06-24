import os
import json
import logging
import datetime
import time
import threading
import base64
import io
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import qrcode

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
            logger.info(f"Carregados {len(gastos)} gastos do arquivo")
        else:
            gastos = []
            logger.info("Nenhum arquivo de dados encontrado, iniciando vazio")
    except Exception as e:
        logger.error(f"Erro ao carregar gastos: {e}")
        gastos = []

def save_gastos():
    """Salva os gastos no arquivo JSON"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(gastos, f, ensure_ascii=False, indent=2)
        logger.info(f"Salvos {len(gastos)} gastos")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar gastos: {e}")
        return False

def parse_date(date_str):
    """Converte data string para objeto datetime"""
    try:
        if not date_str:
            return None
        if '/' in date_str:
            parts = date_str.split('/')
            if len(parts) == 3:
                day = int(parts[0])
                month = int(parts[1])
                year = int(parts[2])
                if year < 100:
                    year += 2000
                return datetime.datetime(year, month, day)
    except Exception as e:
        logger.error(f"Erro ao parsear data {date_str}: {e}")
    return None

def calculate_days_until(date_str):
    """Calcula dias até uma data"""
    try:
        target = parse_date(date_str)
        if target:
            today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            target = target.replace(hour=0, minute=0, second=0, microsecond=0)
            delta = (target - today).days
            return delta
    except Exception as e:
        logger.error(f"Erro ao calcular dias: {e}")
    return None

def get_chrome_driver():
    """Obtém o driver do Chrome configurado"""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1280,720')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Usar webdriver-manager para gerenciar o ChromeDriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        return driver
    except Exception as e:
        logger.error(f"Erro ao criar ChromeDriver: {e}")
        # Tentar sem webdriver-manager
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            
            driver = webdriver.Chrome(options=chrome_options)
            return driver
        except Exception as e2:
            logger.error(f"Erro ao criar ChromeDriver (fallback): {e2}")
            return None

def send_whatsapp_message(message):
    """Envia mensagem via WhatsApp Web usando Selenium"""
    driver = None
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        logger.info("Preparando para enviar mensagem via WhatsApp Web...")
        
        # Obter driver
        driver = get_chrome_driver()
        if not driver:
            logger.error("Não foi possível criar o ChromeDriver")
            return False
        
        # Acessar WhatsApp Web
        driver.get('https://web.whatsapp.com')
        logger.info("Aguardando carregamento do WhatsApp Web...")
        
        # Carregar sessão se existir
        if os.path.exists(WHATSAPP_SESSION):
            try:
                with open(WHATSAPP_SESSION, 'r') as f:
                    cookies = json.load(f)
                for cookie in cookies:
                    try:
                        driver.add_cookie(cookie)
                    except:
                        pass
                driver.refresh()
                logger.info("Sessão carregada")
            except Exception as e:
                logger.warning(f"Erro ao carregar sessão: {e}")
        
        # Aguardar carregar
        wait = WebDriverWait(driver, 90)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='chat-list']")))
        logger.info("WhatsApp Web carregado com sucesso")
        
        # Abrir chat com o número
        phone = TARGET_PHONE
        if not phone.startswith('55'):
            phone = f'55{phone}'
        phone_clean = ''.join(filter(str.isdigit, phone))
        
        chat_url = f'https://web.whatsapp.com/send?phone={phone_clean}'
        driver.get(chat_url)
        logger.info(f"Abrindo chat com {phone_clean}")
        
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
        
        # Enviar
        send_button = driver.find_element(By.CSS_SELECTOR, "button[data-testid='compose-btn-send']")
        send_button.click()
        
        logger.info(f"Mensagem enviada com sucesso: {message[:50]}...")
        
        # Salvar sessão
        try:
            cookies = driver.get_cookies()
            with open(WHATSAPP_SESSION, 'w') as f:
                json.dump(cookies, f)
            logger.info("Sessão salva")
        except Exception as e:
            logger.warning(f"Erro ao salvar sessão: {e}")
        
        driver.quit()
        return True
        
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return False

def check_payments():
    """Verifica vencimentos e envia lembretes"""
    global gastos
    
    try:
        logger.info("=" * 50)
        logger.info("INICIANDO VERIFICAÇÃO DE VENCIMENTOS")
        logger.info("=" * 50)
        
        today = datetime.datetime.now().date()
        messages_sent = 0
        pending_count = 0
        
        for gasto in gastos:
            if gasto.get('pago', False):
                continue
            
            data_pagamento = gasto.get('data_pagamento', '')
            if not data_pagamento:
                continue
            
            days_until = calculate_days_until(data_pagamento)
            if days_until is None:
                continue
            
            pending_count += 1
            logger.info(f"Conta: {gasto['nome']} - Vence em {days_until} dias - Data: {data_pagamento}")
            
            message = None
            if days_until == 5:
                message = f"⚠️ Lembrete: A conta {gasto['nome']} vence em 5 dias. Valor: R$ {gasto['valor']}"
            elif days_until == 1:
                message = f"⚠️ Amanhã vence a conta {gasto['nome']}. Valor: R$ {gasto['valor']}"
            elif days_until == 0:
                message = f"🚨 Hoje vence a conta {gasto['nome']}. Valor: R$ {gasto['valor']}"
            elif days_until < 0:
                # Vencido
                message = f"🔴 ATENÇÃO: A conta {gasto['nome']} está vencida há {-days_until} dias! Valor: R$ {gasto['valor']}"
            
            if message:
                logger.info(f"Enviando lembrete: {message}")
                success = send_whatsapp_message(message)
                if success:
                    messages_sent += 1
                time.sleep(3)  # Pausa entre mensagens
        
        logger.info(f"Total de contas pendentes: {pending_count}")
        logger.info(f"Total de mensagens enviadas: {messages_sent}")
        logger.info("=" * 50)
            
    except Exception as e:
        logger.error(f"Erro ao verificar pagamentos: {e}")

def scheduled_job():
    """Job agendado para as 08:00"""
    logger.info("=" * 50)
    logger.info("EXECUTANDO JOB AGENDADO - 08:00")
    logger.info("=" * 50)
    check_payments()

# ==================== ROTAS DA API ====================

@app.route('/')
def index():
    """Serve a página principal"""
    try:
        return send_from_directory('.', 'index.html')
    except Exception as e:
        logger.warning(f"Erro ao servir index.html: {e}")
        return """
        <h1>Sistema de Lembretes Financeiros</h1>
        <p>API está rodando!</p>
        <p>Acesse: <a href="/api/gastos">/api/gastos</a></p>
        """

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
        
        if not novos_gastos:
            return jsonify({'status': 'success', 'count': 0, 'message': 'Nenhum gasto para sincronizar'})
        
        # Processar dados
        for gasto in novos_gastos:
            if not gasto.get('id'):
                gasto['id'] = str(int(time.time() * 1000)) + str(len(gastos))
            gasto['pago'] = gasto.get('pago', False)
            # Limpar dados
            if 'valor' in gasto and gasto['valor']:
                gasto['valor'] = gasto['valor'].replace('R$', '').strip()
        
        # Atualizar ou adicionar
        added = 0
        updated = 0
        
        for novo_gasto in novos_gastos:
            exists = False
            for i, gasto in enumerate(gastos):
                if (gasto.get('nome') == novo_gasto.get('nome') and 
                    gasto.get('data_pagamento') == novo_gasto.get('data_pagamento')):
                    # Atualizar mantendo status de pagamento
                    novo_gasto['pago'] = gasto.get('pago', False)
                    gastos[i] = novo_gasto
                    exists = True
                    updated += 1
                    break
            if not exists:
                gastos.append(novo_gasto)
                added += 1
        
        save_gastos()
        
        logger.info(f"Sincronização concluída: {added} adicionados, {updated} atualizados")
        return jsonify({
            'status': 'success',
            'added': added,
            'updated': updated,
            'total': len(gastos)
        })
        
    except Exception as e:
        logger.error(f"Erro ao sincronizar: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/gastos/<gasto_id>/pagar', methods=['POST'])
def marcar_pago(gasto_id):
    """Marca um gasto como pago"""
    try:
        gasto_id = str(gasto_id)
        for gasto in gastos:
            if str(gasto.get('id')) == gasto_id:
                gasto['pago'] = True
                save_gastos()
                logger.info(f"Gasto {gasto['nome']} marcado como pago")
                return jsonify({'status': 'success', 'message': 'Gasto marcado como pago'})
        return jsonify({'error': 'Gasto não encontrado'}), 404
    except Exception as e:
        logger.error(f"Erro ao marcar como pago: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/gastos/<gasto_id>/nao-pago', methods=['POST'])
def marcar_nao_pago(gasto_id):
    """Marca um gasto como não pago"""
    try:
        gasto_id = str(gasto_id)
        for gasto in gastos:
            if str(gasto.get('id')) == gasto_id:
                gasto['pago'] = False
                save_gastos()
                logger.info(f"Gasto {gasto['nome']} marcado como não pago")
                return jsonify({'status': 'success', 'message': 'Gasto marcado como não pago'})
        return jsonify({'error': 'Gasto não encontrado'}), 404
    except Exception as e:
        logger.error(f"Erro ao marcar como não pago: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/whatsapp/status', methods=['GET'])
def get_whatsapp_status():
    """Retorna status do WhatsApp"""
    session_exists = os.path.exists(WHATSAPP_SESSION)
    return jsonify({
        'connected': session_exists,
        'session_exists': session_exists,
        'message': 'Sessão ativa' if session_exists else 'Sessão não encontrada'
    })

@app.route('/api/whatsapp/connect', methods=['POST'])
def connect_whatsapp():
    """Conecta ao WhatsApp e retorna QR Code"""
    driver = None
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        logger.info("Gerando QR Code para WhatsApp...")
        
        # Obter driver
        driver = get_chrome_driver()
        if not driver:
            return jsonify({'error': 'Não foi possível iniciar o navegador'}), 500
        
        # Acessar WhatsApp Web
        driver.get('https://web.whatsapp.com')
        logger.info("Aguardando QR Code...")
        
        time.sleep(5)
        
        # Capturar QR Code
        try:
            qr_element = WebDriverWait(driver, 45).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='qrcode']"))
            )
        except:
            # Tentar seletor alternativo
            try:
                qr_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "canvas[aria-label='Scan me!']"))
                )
            except:
                qr_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@data-testid='qrcode']//canvas"))
                )
        
        # Obter dados do QR Code
        qr_data = None
        try:
            qr_data = qr_element.get_attribute('data-ref')
        except:
            pass
        
        if not qr_data:
            # Tentar capturar via JavaScript
            try:
                qr_data = driver.execute_script("""
                    var qr = document.querySelector('[data-testid="qrcode"]');
                    return qr ? qr.getAttribute('data-ref') : null;
                """)
            except:
                pass
        
        if qr_data:
            # Gerar QR Code
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            
            # Fechar driver
            driver.quit()
            
            logger.info("QR Code gerado com sucesso")
            return jsonify({
                'qrcode': img_base64,
                'message': 'Escaneie o QR Code com o WhatsApp'
            })
        else:
            driver.quit()
            return jsonify({'error': 'Não foi possível obter o QR Code'}), 500
        
    except Exception as e:
        logger.error(f"Erro ao conectar WhatsApp: {e}")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/whatsapp/test', methods=['POST'])
def test_whatsapp():
    """Testa envio de mensagem"""
    try:
        data = request.json
        message = data.get('message', '🧪 Teste do sistema de lembretes financeiros!')
        
        logger.info(f"Teste de envio: {message}")
        success = send_whatsapp_message(message)
        
        return jsonify({
            'success': success,
            'message': 'Mensagem enviada com sucesso!' if success else 'Falha ao enviar mensagem'
        })
    except Exception as e:
        logger.error(f"Erro no teste: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/check-payments', methods=['POST'])
def manual_check_payments():
    """Executa verificação manual de pagamentos"""
    try:
        logger.info("Verificação manual iniciada")
        
        # Executar em thread separada para não bloquear
        thread = threading.Thread(target=check_payments)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'success',
            'message': 'Verificação iniciada em segundo plano'
        })
    except Exception as e:
        logger.error(f"Erro na verificação manual: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check para o Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.datetime.now().isoformat(),
        'gastos_count': len(gastos),
        'whatsapp_connected': os.path.exists(WHATSAPP_SESSION)
    })

def init_scheduler():
    """Inicializa o agendador"""
    global scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        
        scheduler = BackgroundScheduler()
        scheduler.add_job(scheduled_job, 'cron', hour=8, minute=0, id='daily_check')
        scheduler.start()
        logger.info("Agendador iniciado - Verificações às 08:00")
        return True
    except Exception as e:
        logger.error(f"Erro ao iniciar agendador: {e}")
        return False

def start_app():
    """Inicializa a aplicação"""
    logger.info("=" * 50)
    logger.info("INICIANDO SISTEMA DE LEMBRETES FINANCEIROS")
    logger.info("=" * 50)
    
    # Carregar dados
    load_gastos()
    
    # Iniciar agendador
    init_scheduler()
    
    # Verificar se há sessão do WhatsApp
    if os.path.exists(WHATSAPP_SESSION):
        logger.info("Sessão do WhatsApp encontrada")
    else:
        logger.info("Nenhuma sessão do WhatsApp encontrada")
    
    logger.info("Sistema iniciado com sucesso!")
    logger.info("Acesse o painel em: /")
    logger.info("=" * 50)

# ==================== INICIALIZAÇÃO ====================

# Iniciar aplicação quando importado (para gunicorn)
start_app()

# ==================== PONTO DE ENTRADA ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
