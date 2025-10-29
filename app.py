import os
import io
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, session
from flask_socketio import SocketIO, join_room, leave_room, emit
from functools import wraps
import json
from datetime import datetime, timedelta
import calendar
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib import colors
import models as dbHandler

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-123')

# Configuração do SocketIO para produção
try:
    import eventlet
    socketio = SocketIO(app, 
                       cors_allowed_origins="*",
                       async_mode='eventlet')
except ImportError:
    socketio = SocketIO(app, 
                       cors_allowed_origins="*",
                       async_mode='threading')

# Database path para produção
if 'RENDER' in os.environ:
    DB_PATH = "/opt/render/project/src/database/atas.db"
else:
    DB_PATH = "database/atas.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with app.app_context():
        conn = get_db()
        try:
            with open("database/schema.sql") as f:
                conn.executescript(f.read())
            conn.commit()
        except Exception as e:
            print(f"Erro ao inicializar banco: {e}")

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Por favor, faça login para acessar esta página.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Authentication function
def authenticate_user(username, password):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?", 
        (username, password)
    ).fetchone()
    conn.close()
    return user

def get_discursantes_recentes():
    """Busca discursantes dos últimos 2 meses"""
    conn = get_db()
    
    # Data de 2 meses atrás
    dois_meses_atras = (datetime.now().replace(day=1) - timedelta(days=60)).strftime("%Y-%m-%d")
    
    discursantes = conn.execute("""
        SELECT s.discursantes, a.data 
        FROM sacramental s 
        JOIN atas a ON s.ata_id = a.id 
        WHERE a.data >= ? AND a.tipo = 'sacramental'
        ORDER BY a.data DESC
    """, (dois_meses_atras,)).fetchall()
    
    # Processar e consolidar discursantes
    todos_discursantes = []
    for row in discursantes:
        if row['discursantes']:
            try:
                discursantes_lista = json.loads(row['discursantes'])
                for discursante in discursantes_lista:
                    if discursante and discursante.strip():
                        todos_discursantes.append({
                            'nome': discursante.strip(),
                            'data': row['data']
                        })
            except json.JSONDecodeError:
                continue
    
    return todos_discursantes

def get_proxima_reuniao_sacramental():
    """Encontra a data da próxima reunião sacramental"""
    hoje = datetime.now().date()
    
    # Encontrar próximo domingo
    dias_para_domingo = (6 - hoje.weekday()) % 7
    if dias_para_domingo == 0:  # Se hoje é domingo
        dias_para_domingo = 7
    
    proximo_domingo = hoje + timedelta(days=dias_para_domingo)
    
    # Verificar se já existe ata para esta data
    conn = get_db()
    ata_existente = conn.execute(
        "SELECT * FROM atas WHERE data = ? AND tipo = 'sacramental'", 
        (proximo_domingo.strftime("%Y-%m-%d"),)
    ).fetchone()
    
    # Formatar data em português
    data_formatada = proximo_domingo.strftime("%d/%m/%Y")
    
    return {
        'data': proximo_domingo.strftime("%Y-%m-%d"),
        'data_formatada': data_formatada,
        'ata_existente': bool(ata_existente),
        'ata_id': ata_existente['id'] if ata_existente else None
    }

@app.route('/', methods=['GET', 'POST'])
def login():
    # If user is already logged in, redirect to index
    if session.get('logged_in'):
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Por favor, preencha todos os campos.', 'error')
            return render_template('login.html')
        
        user = authenticate_user(username, password)
        
        if user:
            session['logged_in'] = True
            session['username'] = user['username']
            session['user_id'] = user['id']
            flash(f'Login realizado com sucesso! Bem-vindo, {user["username"]}.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Credenciais inválidas. Por favor, tente novamente.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu do sistema.', 'success')
    return redirect(url_for('login'))

@app.route('/index')
@login_required
def index():
    conn = get_db()
    
    # Gerar lista de meses para o seletor EM PORTUGUÊS
    meses = []
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # Nomes dos meses em português
    meses_ptbr = [
        '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
    ]
    
    for month in range(1, 13):
        month_name = meses_ptbr[month]
        month_value = f"{current_year}-{month:02d}"
        meses.append({
            'value': month_value,
            'nome': f"{month_name} {current_year}"
        })
    
    # Formato do mês atual para seleção automática
    mes_atual = datetime.now().strftime("%Y-%m")
    mes_selecionado_nome = meses_ptbr[datetime.now().month] + " " + str(datetime.now().year)
    
    # Carregar atas do mês atual da ala do usuário
    atas = conn.execute(
        "SELECT * FROM atas WHERE strftime('%Y-%m', data) = ? AND ala_id = ? ORDER BY data DESC", 
        (mes_atual, session['user_id'])
    ).fetchall()
    
    # Buscar próxima reunião sacramental
    proxima_reuniao = get_proxima_reuniao_sacramental()
    
    return render_template("index.html", 
                         meses=meses, 
                         mes_atual=mes_atual,
                         mes_selecionado_nome=mes_selecionado_nome,
                         atas=atas,
                         proxima_reuniao=proxima_reuniao)

@app.route("/ata/editar/<int:ata_id>")
@login_required
def editar_ata(ata_id):
    """Rota para editar uma ata existente"""
    conn = get_db()
    ata = conn.execute(
        "SELECT * FROM atas WHERE id=? AND ala_id=?", 
        (ata_id, session['user_id'])
    ).fetchone()
    
    if not ata:
        flash("Ata não encontrada ou você não tem permissão para editá-la.", "error")
        return redirect(url_for('index'))
    
    # Redireciona para o formulário apropriado com os dados existentes
    if ata["tipo"] == "sacramental":
        return redirect(url_for("form_ata", tipo="sacramental", data=ata["data"], editar=ata_id))
    else:
        return redirect(url_for("form_ata", tipo="batismo", data=ata["data"], editar=ata_id))

@app.route("/ata/excluir/<int:ata_id>")
@login_required
def excluir_ata(ata_id: int):
    """Rota para excluir uma ata"""
    conn = get_db()
    
    # Primeiro, exclui os detalhes específicos
    ata = conn.execute("SELECT * FROM atas WHERE id=?", (ata_id,)).fetchone()
    if ata:
        if ata["tipo"] == "sacramental":
            conn.execute("DELETE FROM sacramental WHERE ata_id=?", (ata_id,))
        else:
            conn.execute("DELETE FROM batismo WHERE ata_id=?", (ata_id,))
        
        # Depois exclui a ata principal
        conn.execute("DELETE FROM atas WHERE id=?", (ata_id,))
        conn.commit()
        flash("Ata excluída com sucesso!", "success")
    else:
        flash("Ata não encontrada", "error")
    
    # Always return a redirect response
    return redirect(url_for("index"))


@app.route("/atas/mes/<string:mes>")
@login_required
def listar_atas_mes(mes):
    conn = get_db()
    
    try:
        # Validar formato do mês (YYYY-MM)
        datetime.strptime(mes, "%Y-%m")
        
        atas = conn.execute(
            "SELECT * FROM atas WHERE strftime('%Y-%m', data) = ? AND ala_id = ? ORDER BY data DESC", 
            (mes, session['user_id'])
        ).fetchall()
        
        # Formatar nome do mês para exibição EM PORTUGUÊS
        meses_ptbr = [
            '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
            'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
        ]
        data_mes = datetime.strptime(mes, "%Y-%m")
        mes_nome = meses_ptbr[data_mes.month] + " " + str(data_mes.year)
        
        return render_template("_atas_list.html", 
                             atas=atas, 
                             mes_selecionado_nome=mes_nome)
    
    except ValueError:
        return "<div class='info-card'>Mês inválido.</div>"

@app.template_filter('loads')
def json_loads_filter(s: str) -> list:
    """Template filter to parse JSON strings - always returns a list"""
    if not s:
        return []
    try:
        result = json.loads(s)
        # Ensure we always return a list, even if JSON contains other types
        if isinstance(result, list):
            return result
        else:
            return [result] if result is not None else []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

@app.route("/ata/nova", methods=["GET", "POST"])
@login_required
def nova_ata():
    if request.method == "POST":
        tipo = request.form.get("tipo")
        data = request.form.get("data")
        
        # Validação básica
        if not tipo or not data:
            flash("Erro: Tipo e data são obrigatórios", "error")
            return render_template("nova_ata.html")
            
        # Validação de data - APENAS VERIFICA SE É UMA DATA VÁLIDA
        try:
            datetime.strptime(data, "%Y-%m-%d")
        except ValueError:
            flash("Erro: Data inválida", "error")
            return render_template("nova_ata.html")
            
        return redirect(url_for("form_ata", tipo=tipo, data=data))
    
    # Data padrão: próximo domingo ou hoje se for domingo
    hoje = datetime.now().date()
    dias_para_domingo = (6 - hoje.weekday()) % 7
    if dias_para_domingo == 0:  # Se hoje é domingo
        data_padrao = hoje.strftime("%Y-%m-%d")
    else:
        data_padrao = (hoje + timedelta(days=dias_para_domingo)).strftime("%Y-%m-%d")
    
    return render_template("nova_ata.html", data_padrao=data_padrao)

# In your form_ata route, when creating new atas:
@app.route("/ata/form", methods=["GET", "POST"])
@login_required
def form_ata():
    if request.method == "POST":
        tipo = request.form.get("tipo")
        data = request.form.get("data")
        ata_id_editar = request.form.get("editar")
        
        # ... existing validation code ...
        
        conn = get_db()
        
        if ata_id_editar:
            # Modo edição - verificar se a ata pertence à ala do usuário
            ata_existente = conn.execute(
                "SELECT * FROM atas WHERE id = ? AND ala_id = ?", 
                (ata_id_editar, session['user_id'])
            ).fetchone()
            
            if not ata_existente:
                flash("Você não tem permissão para editar esta ata.", "error")
                return redirect(url_for('index'))
            
            # Atualiza a ata existente
            conn.execute("UPDATE atas SET tipo=?, data=? WHERE id=?", (tipo, data, ata_id_editar))
            ata_id = ata_id_editar
        else:
            # Modo criação - insere nova ata com ala_id
            conn.execute(
                "INSERT INTO atas (tipo, data, ala_id) VALUES (?, ?, ?)", 
                (tipo, data, session['user_id'])
            )
            ata_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        if tipo == "sacramental":
            discursantes = request.form.getlist("discursantes[]")
            # Filtrar discursantes vazios
            discursantes = [d for d in discursantes if d and d.strip()]
            
            anuncios = request.form.getlist("anuncios[]")
            # Filtrar anúncios vazios
            anuncios = [a for a in anuncios if a and a.strip()]
            
            detalhes = {
                "presidido": request.form.get("presidido", ""),
                "dirigido": request.form.get("dirigido", ""),
                "pianista": request.form.get("pianista", ""),  # NOVO CAMPO
                "regente_musica": request.form.get("regente_musica", ""),
                "anuncios": anuncios,  # NOVO CAMPO
                "hino_abertura": request.form.get("hino_abertura", ""),
                "oracao_abertura": request.form.get("oracao_abertura", ""),
                "hino_sacramental": request.form.get("hino_sacramental", ""),
                "hino_intermediario": request.form.get("hino_intermediario", ""),
                "hino_encerramento": request.form.get("hino_encerramento", ""),
                "oracao_encerramento": request.form.get("oracao_encerramento", ""),
                "discursantes": discursantes
            }
            
            if ata_id_editar:
                # Atualiza registro existente
                conn.execute("""
                    UPDATE sacramental 
                    SET presidido=?, dirigido=?, pianista=?, regente_musica=?, anuncios=?, hinos=?, oracoes=?, discursantes=?, hino_sacramental=?, hino_intermediario=?
                    WHERE ata_id=?
                """, (
                    detalhes["presidido"], 
                    detalhes["dirigido"],
                    detalhes["pianista"],  # NOVO
                    detalhes["regente_musica"],
                    json.dumps(detalhes["anuncios"]),  # NOVO
                    json.dumps([detalhes["hino_abertura"], detalhes["hino_encerramento"]]), 
                    json.dumps([detalhes["oracao_abertura"], detalhes["oracao_encerramento"]]), 
                    json.dumps(detalhes["discursantes"]),
                    detalhes["hino_sacramental"],
                    detalhes["hino_intermediario"],
                    ata_id
                ))
            else:
                # Insere novo registro
                conn.execute("""
                    INSERT INTO sacramental (ata_id, presidido, dirigido, pianista, regente_musica, anuncios, hinos, oracoes, discursantes, hino_sacramental, hino_intermediario) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ata_id, 
                    detalhes["presidido"], 
                    detalhes["dirigido"],
                    detalhes["pianista"],  # NOVO
                    detalhes["regente_musica"],
                    json.dumps(detalhes["anuncios"]),  # NOVO
                    json.dumps([detalhes["hino_abertura"], detalhes["hino_encerramento"]]), 
                    json.dumps([detalhes["oracao_abertura"], detalhes["oracao_encerramento"]]), 
                    json.dumps(detalhes["discursantes"]),
                    detalhes["hino_sacramental"],
                    detalhes["hino_intermediario"]
                ))
        
        elif tipo == "batismo":
            batizados = request.form.getlist("batizados[]")
            # Filtrar batizados vazios
            batizados = [b for b in batizados if b and b.strip()]
            
            detalhes = {
                "presidido": request.form.get("presidido", ""),
                "dirigido": request.form.get("dirigido", ""),
                "dedicado": request.form.get("dedicado", ""),
                "testemunha1": request.form.get("testemunha1", ""),
                "testemunha2": request.form.get("testemunha2", ""),
                "batizados": batizados
            }
            
            if ata_id_editar:
                # Atualiza registro existente
                conn.execute("""
                    UPDATE batismo 
                    SET dedicado=?, presidido=?, dirigido=?, batizados=?, testemunha1=?, testemunha2=? 
                    WHERE ata_id=?
                """, (
                    detalhes["dedicado"], 
                    detalhes["presidido"], 
                    detalhes["dirigido"], 
                    json.dumps(detalhes["batizados"]), 
                    detalhes["testemunha1"], 
                    detalhes["testemunha2"], 
                    ata_id
                ))
            else:
                # Insere novo registro
                conn.execute("""
                    INSERT INTO batismo (ata_id, dedicado, presidido, dirigido, batizados, testemunha1, testemunha2) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    ata_id, 
                    detalhes["dedicado"], 
                    detalhes["presidido"], 
                    detalhes["dirigido"], 
                    json.dumps(detalhes["batizados"]), 
                    detalhes["testemunha1"], 
                    detalhes["testemunha2"]
                ))
        
        conn.commit()
        flash("Ata salva com sucesso!", "success")
        return redirect(url_for("visualizar_ata", ata_id=ata_id))

    # GET request
    tipo = request.args.get("tipo")
    data = request.args.get("data")
    editar = request.args.get("editar")
    
    # Lógica para carregar dados existentes se estiver editando
    dados_existentes = {}
    if editar:
        conn = get_db()
        if tipo == "sacramental":
            dados = conn.execute("SELECT * FROM sacramental WHERE ata_id=?", (editar,)).fetchone()
            if dados:
                dados_existentes = dict(dados)
                # Converter JSON strings de volta para objetos
                if dados_existentes.get('hinos'):
                    hinos = json.loads(dados_existentes['hinos'])
                    dados_existentes['hino_abertura'] = hinos[0] if len(hinos) > 0 else ''
                    dados_existentes['hino_encerramento'] = hinos[1] if len(hinos) > 1 else ''
                if dados_existentes.get('oracoes'):
                    oracoes = json.loads(dados_existentes['oracoes'])
                    dados_existentes['oracao_abertura'] = oracoes[0] if len(oracoes) > 0 else ''
                    dados_existentes['oracao_encerramento'] = oracoes[1] if len(oracoes) > 1 else ''
                if dados_existentes.get('discursantes'):
                    dados_existentes['discursantes'] = json.loads(dados_existentes['discursantes'])
                if dados_existentes.get('anuncios'):
                    dados_existentes['anuncios'] = json.loads(dados_existentes['anuncios'])
        else:
            dados = conn.execute("SELECT * FROM batismo WHERE ata_id=?", (editar,)).fetchone()
            if dados:
                dados_existentes = dict(dados)
                if dados_existentes.get('batizados'):
                    dados_existentes['batizados'] = json.loads(dados_existentes['batizados'])
    
    if not tipo or not data:
        flash("Erro: Tipo e data são obrigatórios", "error")
        return redirect(url_for("nova_ata"))
    
    if tipo == "sacramental":
        dt = datetime.strptime(data, "%Y-%m-%d")
        primeiro_domingo = min([d for d in range(1, 8) if calendar.weekday(dt.year, dt.month, d) == 6])
        is_primeiro_domingo = dt.day == primeiro_domingo
        
        # Buscar discursantes recentes apenas para sacramental (apenas em modo criação)
        discursantes_recentes = get_discursantes_recentes() if not editar else []
        
        return render_template("sacramental.html", 
                             primeiro=is_primeiro_domingo, 
                             data=data, 
                             editar=editar, 
                             dados=dados_existentes,
                             discursantes_recentes=discursantes_recentes)
    elif tipo == "batismo":
        return render_template("batismo.html", 
                             data=data, 
                             editar=editar, 
                             dados=dados_existentes)
    else:
        flash("Tipo de ata não reconhecido", "error")
        return redirect(url_for("nova_ata"))

@app.route("/ata/<int:ata_id>")
@login_required
def visualizar_ata(ata_id):
    conn = get_db()
    ata = conn.execute(
        "SELECT * FROM atas WHERE id=? AND ala_id=?", 
        (ata_id, session['user_id'])
    ).fetchone()
    
    if not ata:
        flash("Ata não encontrada ou você não tem permissão para visualizá-la.", "error")
        return redirect(url_for("index"))
        
    if ata["tipo"] == "sacramental":
        detalhes = conn.execute("SELECT * FROM sacramental WHERE ata_id=?", (ata_id,)).fetchone()
        if detalhes:
            # Converter para dicionário para facilitar o acesso
            detalhes_dict = dict(detalhes)
            if detalhes_dict.get('hinos'):
                hinos = json.loads(detalhes_dict['hinos'])
                detalhes_dict['hino_abertura'] = hinos[0] if len(hinos) > 0 else ''
                detalhes_dict['hino_encerramento'] = hinos[1] if len(hinos) > 1 else ''
            if detalhes_dict.get('oracoes'):
                oracoes = json.loads(detalhes_dict['oracoes'])
                detalhes_dict['oracao_abertura'] = oracoes[0] if len(oracoes) > 0 else ''
                detalhes_dict['oracao_encerramento'] = oracoes[1] if len(oracoes) > 1 else ''
            if detalhes_dict.get('discursantes'):
                detalhes_dict['discursantes'] = json.loads(detalhes_dict['discursantes'])
            if detalhes_dict.get('anuncios'):
                detalhes_dict['anuncios'] = json.loads(detalhes_dict['anuncios'])
            detalhes = detalhes_dict
    else:
        detalhes = conn.execute("SELECT * FROM batismo WHERE ata_id=?", (ata_id,)).fetchone()
        if detalhes:
            detalhes_dict = dict(detalhes)
            if detalhes_dict.get('batizados'):
                detalhes_dict['batizados'] = json.loads(detalhes_dict['batizados'])
            detalhes = detalhes_dict
    
    return render_template("visualizar_ata.html", ata=ata, detalhes=detalhes or {})

@app.route("/ata/exportar/<int:ata_id>")
@login_required
def exportar_pdf(ata_id):
    conn = get_db()
    ata = conn.execute("SELECT * FROM atas WHERE id=?", (ata_id,)).fetchone()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont("Helvetica", 14)
    c.drawString(50, 800, f"Ata de {ata['tipo'].capitalize()} - {ata['data']}")
    c.setFont("Helvetica", 12)

    if ata["tipo"] == "sacramental":
        detalhes = conn.execute("SELECT * FROM sacramental WHERE ata_id=?", (ata_id,)).fetchone()
        if detalhes:
            # Converter para dicionário para evitar o erro do .get()
            detalhes_dict = dict(detalhes)
            hinos = json.loads(detalhes_dict["hinos"])
            oracoes = json.loads(detalhes_dict["oracoes"])
            discursantes = json.loads(detalhes_dict["discursantes"])
            anuncios = json.loads(detalhes_dict["anuncios"]) if detalhes_dict.get("anuncios") else []
            
            c.drawString(50, 770, f"Presidido por: {detalhes_dict['presidido']}")
            c.drawString(50, 750, f"Dirigido por: {detalhes_dict['dirigido']}")
            c.drawString(50, 730, f"Pianista: {detalhes_dict.get('pianista', '')}")  # NOVO
            c.drawString(50, 710, f"Regente de Música: {detalhes_dict.get('regente_musica', '')}")
            
            # Anúncios
            y = 690
            if anuncios and len(anuncios) > 0:
                c.drawString(50, 690, "Anúncios:")
                y = 670
                for a in anuncios:
                    c.drawString(70, y, f"- {a}")
                    y -= 20
            
            c.drawString(50, y-20, f"Hino de Abertura: {hinos[0] if len(hinos) > 0 else ''}")
            c.drawString(50, y-40, f"Oração de Abertura: {oracoes[0] if len(oracoes) > 0 else ''}")
            c.drawString(50, y-60, f"Hino Sacramental: {detalhes_dict.get('hino_sacramental', '')}")
            
            # Discursantes
            y_disc = y-80
            if discursantes and len(discursantes) > 0:
                c.drawString(50, y_disc, "Discursantes:")
                y_disc -= 20
                for d in discursantes:
                    c.drawString(70, y_disc, f"- {d}")
                    y_disc -= 20
            
            c.drawString(50, y_disc-20, f"Hino Intermediário: {detalhes_dict.get('hino_intermediario', '')}")
            c.drawString(50, y_disc-40, f"Hino de Encerramento: {hinos[1] if len(hinos) > 1 else ''}")
            c.drawString(50, y_disc-60, f"Oração de Encerramento: {oracoes[1] if len(oracoes) > 1 else ''}")
    else:
        detalhes = conn.execute("SELECT * FROM batismo WHERE ata_id=?", (ata_id,)).fetchone()
        if detalhes:
            # Converter para dicionário para evitar o erro do .get()
            detalhes_dict = dict(detalhes)
            batizados = json.loads(detalhes_dict["batizados"])
            c.drawString(50, 770, f"Presidido por: {detalhes_dict['presidido']}")
            c.drawString(50, 750, f"Dirigido por: {detalhes_dict['dirigido']}")
            c.drawString(50, 730, f"Dedicado a: {detalhes_dict['dedicado']}")
            c.drawString(50, 710, f"Testemunha 1: {detalhes_dict.get('testemunha1', '')}")
            c.drawString(50, 690, f"Testemunha 2: {detalhes_dict.get('testemunha2', '')}")
            y = 670
            if batizados and len(batizados) > 0:
                c.drawString(50, 670, "Batizados:")
                y = 650
                for b in batizados:
                    c.drawString(70, y, f"- {b}")
                    y -= 20

    c.showPage()
    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"ata_{ata_id}.pdf", mimetype="application/pdf")

@app.route("/ata/exportar_sacramental/<int:ata_id>")
@login_required
def exportar_sacramental_pdf(ata_id):
    conn = get_db()
    ata = conn.execute("SELECT * FROM atas WHERE id=?", (ata_id,)).fetchone()
    
    if not ata or ata["tipo"] != "sacramental":
        flash("Ata sacramental não encontrada", "error")
        return redirect(url_for("index"))
    
    detalhes = conn.execute("SELECT * FROM sacramental WHERE ata_id=?", (ata_id,)).fetchone()
    if not detalhes:
        flash("Detalhes da ata não encontrados", "error")
        return redirect(url_for("visualizar_ata", ata_id=ata_id))
    
    # Converter para dicionário
    detalhes_dict = dict(detalhes)
    
    # Processar dados
    if detalhes_dict.get('hinos'):
        hinos = json.loads(detalhes_dict['hinos'])
        detalhes_dict['hino_abertura'] = hinos[0] if len(hinos) > 0 else ''
        detalhes_dict['hino_encerramento'] = hinos[1] if len(hinos) > 1 else ''
    
    if detalhes_dict.get('oracoes'):
        oracoes = json.loads(detalhes_dict['oracoes'])
        detalhes_dict['oracao_abertura'] = oracoes[0] if len(oracoes) > 0 else ''
        detalhes_dict['oracao_encerramento'] = oracoes[1] if len(oracoes) > 1 else ''
    
    if detalhes_dict.get('discursantes'):
        detalhes_dict['discursantes'] = json.loads(detalhes_dict['discursantes'])
    
    if detalhes_dict.get('anuncios'):
        detalhes_dict['anuncios'] = json.loads(detalhes_dict['anuncios'])
    
    buffer = io.BytesIO()
    
    # Criar PDF com duas páginas
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # CORES - Baseadas no site da Igreja
    AZUL_IGREJA = colors.HexColor("#004272")  # Azul escuro
    AZUL_CLARO = colors.HexColor("#E6F2FF")   # Azul claro para fundos
    CINZA_CLARO = colors.HexColor("#F8F9FA")  # Cinza muito claro
    
    # ========== PÁGINA 1 (FRENTE) ==========
    c.setFillColor(AZUL_IGREJA)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(180, height - 50, "ATA REUNIÃO SACRAMENTAL")
    
    
    # Tabela de informações
    data_ata = datetime.strptime(ata['data'], "%Y-%m-%d")
    data_formatada = data_ata.strftime("%d/%m/%Y")
    
    table_data = [
        ["ALA [nome]", "ESTACA CRICIÚMA", f"HORÁRIO [editar]", f"DATA {data_formatada}"]
    ]
    
    jooj = 125

    table = Table(table_data, colWidths=[jooj, jooj, jooj, jooj])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), AZUL_IGREJA),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.white),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    table.wrapOn(c, width, height)
    table.drawOn(c, 50, height - 100)
    
    font_a = 12

    # Boas-vindas
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 13)
    texto_boas_vindas = f"Bom dia irmãos e irmãs! Gostaríamos de fazer todos muito bem vindos a mais uma Reunião Sacramental da ALA [nome], Estaca Criciúma, neste dia {data_formatada}. Desejamos que todos se sintam bem entre nós, especialmente aqueles que nos visitam."
    
    estilo_paragrafo = ParagraphStyle(
        'Normal',
        fontName='Helvetica',
        fontSize=13,
        leading=12,
        alignment=4,  # Justificado
        textColor=colors.black,
        spaceBefore=15,
        spaceAfter=12
    )
    
    p = Paragraph(texto_boas_vindas, estilo_paragrafo)
    p.wrapOn(c, width - 100, height)
    p.drawOn(c, 50, height - 160)
    
    # Informações de presidência
    y_pos = height - 180
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "Esta Reunião está sendo presidida por:")
    c.setFont("Helvetica", font_a)
    c.drawString(280, y_pos, detalhes_dict.get('presidido', 'Não informado'))
    
    y_pos -= 20
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "E dirigida por:")
    c.setFont("Helvetica", font_a)
    c.drawString(200, y_pos, detalhes_dict.get('dirigido', 'Não informado'))
    
    y_pos -= 20
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "Como recepcionistas:")
    # Aqui você pode adicionar recepcionistas se tiver o campo
    
    y_pos -= 20
    c.drawString(50, y_pos, "Como pianista:")
    c.setFont("Helvetica", font_a)
    c.drawString(200, y_pos, detalhes_dict.get('pianista', 'Não informado'))
    
    y_pos -= 20
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "E regente de música:")
    c.setFont("Helvetica", font_a)
    c.drawString(200, y_pos, detalhes_dict.get('regente_musica', 'Não informado'))
    
    # Linha divisória
    y_pos -= 20
    c.setStrokeColor(colors.HexColor("#E2E8F0"))  # Cinza claro
    c.setLineWidth(3)
    c.line(50, y_pos, width - 50, y_pos)
    y_pos -= 12

    # SEÇÃO: ABERTURA
    y_pos -= 20
    c.setFillColor(AZUL_IGREJA)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, y_pos, "ABERTURA (6 min)")
    
    y_pos -= 32
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold",font_a)
    c.drawString(50, y_pos, "Reconhecemos a Presença:")
    
    y_pos -= 20
    c.drawString(50, y_pos, "Temos como anúncios:")
    
    # Anúncios
    y_pos -= 20
    c.setFont("Helvetica", font_a)
    if detalhes_dict.get('anuncios'):
        for anuncio in detalhes_dict['anuncios']:
            if anuncio and anuncio.strip():
                p_anuncio = Paragraph(f"• {anuncio}", estilo_paragrafo)
                p_anuncio.wrapOn(c, width - 100, height)
                p_anuncio.drawOn(c, 65, y_pos)
                y_pos -= 15
    else:
        c.drawString(65, y_pos, "Nenhum anúncio informado")
        y_pos -= 15
    
    # Hino e Oração de Abertura
    y_pos -= 60
    table_encerramento = Table([
        ["CANTAREMOS O HINO DE ABERTURA:", 
         "E A PRIMEIRA ORAÇÃO SERÁ FEITA POR: "],
        [f"{detalhes_dict.get('hino_abertura', 'Não informado')}", 
         f"{detalhes_dict.get('oracao_abertura', 'Não informado')}"]
    ], colWidths=[250,250,250,250])
    
    table_encerramento.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), AZUL_CLARO),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    table_encerramento.wrapOn(c, width, height)
    table_encerramento.drawOn(c, 50, y_pos - 20)
    
    # Linha divisória
    y_pos -= 30
    c.setStrokeColor(colors.HexColor("#E2E8F0"))  # Cinza claro
    c.setLineWidth(3)
    c.line(50, y_pos, width - 50, y_pos)
    y_pos -= 12

    # SEÇÃO: AÇÕES
    y_pos -= 20
    c.setFillColor(AZUL_IGREJA)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, y_pos, "AÇÕES (5 min)")
    
    y_pos -= 30
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "DESOBRIGAÇÕES")
    
    y_pos -= 20
    c.setFont("Helvetica", 10)
    texto_desobrigacoes = "É proposto dar um voto de agradecimento aos serviços prestados pelo(a) irmã(o) [NOME] que serviu como [CHAMADO]. Todos os que desejam se manifestar, levantem a mão"
    p_desobrigacoes = Paragraph(texto_desobrigacoes, estilo_paragrafo)
    p_desobrigacoes.wrapOn(c, width - 100, height)
    p_desobrigacoes.drawOn(c, 50, y_pos - 30)
    
    y_pos -= 60
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "APOIOS")
    
    y_pos -= 20
    c.setFont("Helvetica", 10)
    texto_apoios = "O(a) irmã(o) [NOME] está sendo chamado(a) como [CHAMADO]. Todos que forem a favor manifestem-se. Os que forem contrários, manifestem-se"
    p_apoios = Paragraph(texto_apoios, estilo_paragrafo)
    p_apoios.wrapOn(c, width - 100, height)
    p_apoios.drawOn(c, 50, y_pos - 20)

    # Confirmações Batismais
    y_pos -= 60
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "CONFIRMAÇÕES BATISMAIS")

    y_pos -= 20
    c.setFont("Helvetica", 10)
    texto_confirmacoes = "O(a) irmã(o) [NOME] foram batizados, gostaríamos de convida-los(a) para virem até o púlpito para que possamos fazer sua confirmação como Membro de A Igreja de Jesus Cristo dos Santos dos Ultimos Dias."
    p_confirmacoes = Paragraph(texto_confirmacoes, estilo_paragrafo)
    p_confirmacoes.wrapOn(c, width - 100, height)
    p_confirmacoes.drawOn(c, 50, y_pos - 20)
    
    c.showPage()  # Fim da página 1
    
    # ========== PÁGINA 2 (VERSO) ==========
    
    # SEÇÃO: AÇÕES (continuação)
    y_pos = height - 50
    c.setFillColor(AZUL_IGREJA)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, y_pos, "AÇÕES (continuação)")
    
    # Apoio a Novos Membros
    y_pos -= 30
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "APOIO A NOVOS MEMBROS")
    
    y_pos -= 15
    c.setFont("Helvetica", 10)
    texto_novos_membros = "O(a) irmã(o) [NOME] foi batizado e confirmado membro da igreja, e gostarámos do apoio de todos os irmãos de plena aceitação como mais novo membro da ala. Todos a favor, manifestem-se"
    p_novos_membros = Paragraph(texto_novos_membros, estilo_paragrafo)
    p_novos_membros.wrapOn(c, width - 100, height)
    p_novos_membros.drawOn(c, 50, y_pos - 40)
    
    # Benção de Crianças
    y_pos -= 70
    c.setFont("Helvetica-Bold", font_a)
    c.drawString(50, y_pos, "BENÇÃO DE CRIANÇAS")
    
    y_pos -= 20
    c.setFont("Helvetica", 10)
    texto_bencao = "Gostaríamos de chamar ao púlpito o irmão [NOME] que irá dar a benção de apresentação da(a) [NOME]"
    p_bencao = Paragraph(texto_bencao, estilo_paragrafo)
    p_bencao.wrapOn(c, width - 100, height)
    p_bencao.drawOn(c, 50, y_pos - 20)
    
    # Linha divisória
    y_pos -= 50
    c.setStrokeColor(colors.HexColor("#E2E8F0"))  # Cinza claro
    c.setLineWidth(3)
    c.line(50, y_pos, width - 50, y_pos)
    y_pos -= 12

    # SEÇÃO: SACRAMENTO
    y_pos -= 20
    c.setFillColor(AZUL_IGREJA)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, y_pos, "SACRAMENTO (10 min)")
    
    y_pos -= 30
    c.setFillColor(colors.black)
    c.setFont("Helvetica", font_a)
    texto_sacramento = f"Passaremos ao Sacramento, que é a parte mais importante de nossa reunião. Cantaremos como Hino Sacramental {detalhes_dict.get('hino_sacramental', 'Não informado')}, o Sacramento será abençoado e distribuído a todos"
    p_sacramento = Paragraph(texto_sacramento, estilo_paragrafo)
    p_sacramento.wrapOn(c, width - 100, height)
    p_sacramento.drawOn(c, 50, y_pos - 20)
    
    y_pos -= 50
    c.setFont("Helvetica-Bold", 10)
    hino_sacramento = f"HINO SACRAMENTAL (3 min): {detalhes_dict.get('hino_sacramental', 'Não informado')}"
    c.drawString(50, y_pos, hino_sacramento)
    
    # Linha divisória
    y_pos -= 20
    c.setStrokeColor(colors.HexColor("#E2E8F0"))  # Cinza claro
    c.setLineWidth(3)
    c.line(50, y_pos, width - 50, y_pos)
    y_pos -= 12

    # SEÇÃO: MENSAGENS
    y_pos -= 20
    c.setFillColor(AZUL_IGREJA)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, y_pos, "MENSAGENS (35 min)")
    
    y_pos -= 20
    c.setFillColor(colors.black)
    c.setFont("Helvetica", font_a)
    texto_mensagens = "Agradecemos a todos pela reverência durante o Sacramento. Passaremos agora a parte dos discursantes. Gostaria de lembrar todos que estejam assitindo a transmissão da reunião, que se identifiquem para que possamos contá-los também"
    p_mensagens = Paragraph(texto_mensagens, estilo_paragrafo)
    p_mensagens.wrapOn(c, width - 100, height)
    p_mensagens.drawOn(c, 50, y_pos - 20)
    
    # Discursantes
    y_pos -= 50
    if detalhes_dict.get('discursantes'):
        discursantes_data = []
        for i, discursante in enumerate(detalhes_dict['discursantes']):
            if discursante and discursante.strip():
                tempo = "3-5 min" if i == 0 else "5-7 min" if i == 1 else "8-10 min"
                discursantes_data.append([f"{i+1}º ORADOR ({tempo})", discursante])
        
        if discursantes_data:
            table_discursantes = Table(discursantes_data, colWidths=[120, 350])
            table_discursantes.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), AZUL_CLARO),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
            ]))
            table_discursantes.wrapOn(c, width, height)
            table_discursantes.drawOn(c, 50, y_pos - len(discursantes_data) * 20)
            y_pos -= len(discursantes_data) * 25
    
    # Hino Intermediário
    if detalhes_dict.get('hino_intermediario'):
        y_pos -= 20
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y_pos, "HINO INTERMEDIÁRIO (3 min):")
        c.setFont("Helvetica", 12)
        c.drawString(230, y_pos, detalhes_dict.get('hino_intermediario', 'Não informado'))
    

    # Linha divisória
    y_pos -= 20
    c.setStrokeColor(colors.HexColor("#E2E8F0"))  # Cinza claro
    c.setLineWidth(3)
    c.line(50, y_pos, width - 50, y_pos)
    y_pos -= 12

    # SEÇÃO: AGRADECIMENTOS FINAIS
    y_pos -= 20
    c.setFillColor(AZUL_IGREJA)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, y_pos, "AGRADECIMENTOS FINAIS")
    
    y_pos -= 40
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 12)
    texto_agradecimentos = f"Agradecemos a presença e participação de todos, especialmente aqueles que contribuíram de alguma forma para que essa reunião acontecesse. E convidamos todos para que estejam aqui no próximo domingo. Ouviremos como último orador o(a) irmã(o) [NOME]. Logo após, cantaremos o hino {detalhes_dict.get('hino_encerramento', 'Não informado')}, e o(a) irmã(o) {detalhes_dict.get('oracao_encerramento', 'Não informado')} oferecerá a última oração. Desejamos a todos uma ótima semana e que o Espírito do Senhor os acompanhe."
    
    p_agradecimentos = Paragraph(texto_agradecimentos, estilo_paragrafo)
    p_agradecimentos.wrapOn(c, width - 100, height)
    p_agradecimentos.drawOn(c, 50, y_pos - 40)
    
    # SEÇÃO: ENCERRAMENTO
    y_pos -= 70
    c.setFillColor(AZUL_IGREJA)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, y_pos, "ENCERRAMENTO (2 min)")
    
    # Hino e Oração de Abertura
    y_pos -= 20
    table_encerramento = Table([
        ["HINO DE ENCERRAMENTO:", 
         "ORAÇÃO DE ENCERRAMENTO:"],
        [f"{detalhes_dict.get('hino_encerramento', 'Não informado')}", 
         f"{detalhes_dict.get('oracao_encerramento', 'Não informado')}"]
    ], colWidths=[250, 250,250,250])
    
    table_encerramento.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), AZUL_CLARO),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    table_encerramento.wrapOn(c, width, height)
    table_encerramento.drawOn(c, 50, y_pos - 20)
    
    c.showPage()
    c.save()
    
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"ata_sacramental_{ata_id}.pdf", mimetype="application/pdf")

# Sistema de mensagens flash
@app.context_processor
def inject_flash_messages():
    messages = []
    # Simulando o sistema de flash messages já que não está configurado
    return dict(flash_messages=messages)

# WebSocket events
users_editing = {}

@socketio.on('join')
def handle_join(data):
    ata_id = data['ata_id']
    users_editing[ata_id] = users_editing.get(ata_id, 0) + 1
    join_room(ata_id)
    emit('update_users', {'count': users_editing[ata_id]}, to=ata_id)

@socketio.on('leave')
def handle_leave(data):
    ata_id = data['ata_id']
    if ata_id in users_editing:
        users_editing[ata_id] = max(users_editing[ata_id] - 1, 0)
        if users_editing[ata_id] == 0:
            del users_editing[ata_id]
        leave_room(ata_id)
        emit('update_users', {'count': users_editing.get(ata_id, 0)}, to=ata_id)

@socketio.on('field_update')
def handle_field_update(data):
    ata_id = data['ata_id']
    emit('field_update', {'name': data['name'], 'value': data['value']}, to=ata_id, include_self=False)


if __name__ == "__main__":
    # Don't run the server on PythonAnywhere
    if 'PYTHONANYWHERE_DOMAIN' in os.environ:
        print("Running on PythonAnywhere - WSGI will handle the server")
        # The WSGI server will handle the app
    else:
        # Only run manually for local development
        port = int(os.environ.get('PORT', 5001))
        debug = os.environ.get('DEBUG', 'False').lower() == 'true'
        
        init_db()
        
        socketio.run(app, 
                     host='0.0.0.0', 
                     port=port,
                     debug=debug,
                     allow_unsafe_werkzeug=True)
