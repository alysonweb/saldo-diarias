import os
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, abort, send_file, jsonify, session)
from flask_login import (LoginManager, login_required, login_user,
                         logout_user, current_user)
from werkzeug.utils import secure_filename
from models import (db, Solicitacao, SaldoDiarias, HistoricoSaldo,
                    HistoricoStatus, Motorista, Usuario, Comentario,
                    Anexo, Configuracao,
                    STATUS_WORKFLOW, REGIOES, ESTADOS_POR_REGIAO,
                    TIPOS_DIARIA, CATEGORIAS, ORGAOS, CORES_REGIAO)
from datetime import datetime, date, timedelta
from calendar import monthrange
from io import BytesIO
import json

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///saldo_diarias.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'saldo-diarias-mds-2026'

# Upload config
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

db.init_app(app)

# Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login_page'
login_manager.login_message = 'Faça login para continuar.'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(uid):
    return Usuario.query.get(int(uid))


TODOS_ESTADOS = sorted([uf for estados in ESTADOS_POR_REGIAO.values() for uf in estados])
MESES_PT = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
            'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']


# ── Decoradores ────────────────────────────────────────────────────────────────

def requer_perfil(*perfis):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.perfil not in perfis:
                flash('Acesso não autorizado.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Migrate DB ─────────────────────────────────────────────────────────────────

def migrate_db():
    """Adiciona colunas novas que possam não existir no banco legado."""
    with db.engine.connect() as conn:
        migrations = [
            "ALTER TABLE solicitacoes ADD COLUMN criado_por_id INTEGER REFERENCES usuarios(id)",
            "ALTER TABLE solicitacoes ADD COLUMN aceite_eletronico BOOLEAN DEFAULT 0",
            "ALTER TABLE solicitacoes ADD COLUMN aceite_data DATETIME",
        ]
        for sql in migrations:
            try:
                conn.execute(db.text(sql))
                conn.commit()
            except Exception:
                pass


# ── Helpers ────────────────────────────────────────────────────────────────────

def proximo_status(status):
    try:
        idx = STATUS_WORKFLOW.index(status)
        if idx < len(STATUS_WORKFLOW) - 1:
            return STATUS_WORKFLOW[idx + 1]
    except ValueError:
        pass
    return None


def get_saldo_ativo():
    return SaldoDiarias.query.filter_by(ativo=True).first()


def comprometer_saldo(sol):
    saldo = get_saldo_ativo()
    if saldo and sol.quantidade_diarias:
        saldo.saldo_comprometido += sol.quantidade_diarias
        db.session.add(HistoricoSaldo(
            tipo='Compromisso',
            quantidade=sol.quantidade_diarias,
            valor=sol.valor_total,
            descricao=f'Comprometido para {sol.numero}',
            saldo_id=saldo.id,
            solicitacao_id=sol.id,
        ))


def atualizar_saldo_por_transicao(sol, status_novo):
    saldo = get_saldo_ativo()
    if not saldo or not sol.quantidade_diarias:
        return
    qty = sol.quantidade_diarias
    if status_novo == 'Concluída':
        saldo.saldo_comprometido = max(0, saldo.saldo_comprometido - qty)
        saldo.saldo_usado += qty
        db.session.add(HistoricoSaldo(
            tipo='Débito', quantidade=qty, valor=sol.valor_total,
            descricao=f'Concluído: {sol.numero}',
            saldo_id=saldo.id, solicitacao_id=sol.id,
        ))
    elif status_novo == 'Cancelada':
        if sol.status not in ('Concluída', 'Cancelada'):
            saldo.saldo_comprometido = max(0, saldo.saldo_comprometido - qty)
            db.session.add(HistoricoSaldo(
                tipo='Liberação', quantidade=qty, valor=sol.valor_total,
                descricao=f'Cancelado: {sol.numero}',
                saldo_id=saldo.id, solicitacao_id=sol.id,
            ))


def registrar_historico_status(sol, status_anterior, status_novo, obs=''):
    db.session.add(HistoricoStatus(
        solicitacao_id=sol.id,
        status_anterior=status_anterior,
        status_novo=status_novo,
        observacao=obs,
    ))


def verificar_conflitos(servidor, data_inicio, data_fim, excluir_id=None):
    """Retorna solicitações do mesmo servidor no mesmo período."""
    if not servidor:
        return []
    query = Solicitacao.query.filter(
        Solicitacao.servidor_responsavel == servidor,
        Solicitacao.status.notin_(['Cancelada']),
        Solicitacao.data_inicio <= data_fim,
        Solicitacao.data_fim >= data_inicio,
    )
    if excluir_id:
        query = query.filter(Solicitacao.id != excluir_id)
    return query.all()


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        matricula = request.form.get('matricula', '').strip()
        senha     = request.form.get('senha', '')
        user = Usuario.query.filter_by(matricula=matricula).first()
        if user and user.ativo and user.check_senha(senha):
            user.ultimo_acesso = datetime.now()
            db.session.commit()
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('Matrícula ou senha inválidos.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout_page():
    logout_user()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('login_page'))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    hoje_d = date.today()
    ativos = (Solicitacao.query
              .filter(Solicitacao.status.notin_(['Concluída', 'Cancelada']))
              .order_by(Solicitacao.data_inicio.asc()).all())

    por_regiao = {r: [s for s in ativos if s.regiao == r] for r in REGIOES}

    vencidos        = [s for s in ativos if s.data_fim < hoje_d]
    iniciando_hoje  = [s for s in ativos if s.data_inicio == hoje_d]
    encerrando_hoje = [s for s in ativos if s.data_fim == hoje_d]

    saldo            = get_saldo_ativo()
    total            = Solicitacao.query.count()
    total_concluidas = Solicitacao.query.filter_by(status='Concluída').count()

    recentes = (Solicitacao.query
                .order_by(Solicitacao.data_criacao.desc()).limit(10).all())

    _dias  = ['segunda-feira','terça-feira','quarta-feira','quinta-feira','sexta-feira','sábado','domingo']
    _meses = ['janeiro','fevereiro','março','abril','maio','junho','julho','agosto','setembro','outubro','novembro','dezembro']
    hoje_str = f"{_dias[hoje_d.weekday()]}, {hoje_d.day:02d} de {_meses[hoje_d.month-1]} de {hoje_d.year}"

    return render_template('index.html',
        ativos=ativos, por_regiao=por_regiao, saldo=saldo, recentes=recentes,
        hoje=hoje_d, hoje_str=hoje_str, regioes=REGIOES, vencidos=vencidos,
        iniciando_hoje=iniciando_hoje, encerrando_hoje=encerrando_hoje,
        total=total, total_concluidas=total_concluidas,
        regioes_labels=REGIOES,
        regioes_data=[len(por_regiao[r]) for r in REGIOES],
    )


# ── Solicitações ──────────────────────────────────────────────────────────────

@app.route('/solicitacoes')
@login_required
def lista_solicitacoes():
    status_f = request.args.get('status', '')
    regiao_f = request.args.get('regiao', '')
    orgao_f  = request.args.get('orgao', '')
    q        = request.args.get('q', '')

    query = Solicitacao.query
    if status_f: query = query.filter_by(status=status_f)
    if regiao_f: query = query.filter_by(regiao=regiao_f)
    if orgao_f:  query = query.filter_by(orgao=orgao_f)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Solicitacao.numero.like(like),
            Solicitacao.servidor_responsavel.like(like),
            Solicitacao.estado.like(like),
            Solicitacao.motorista_nome.like(like),
            Solicitacao.unidade_secretaria.like(like),
        ))

    items = query.order_by(Solicitacao.data_criacao.desc()).all()
    return render_template('solicitacoes/lista.html',
        items=items, status_f=status_f, regiao_f=regiao_f,
        orgao_f=orgao_f, q=q,
        status_list=STATUS_WORKFLOW + ['Cancelada'],
        regioes=REGIOES, orgaos=ORGAOS)


@app.route('/solicitacoes/exportar')
@login_required
def exportar_solicitacoes():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    status_f = request.args.get('status', '')
    regiao_f = request.args.get('regiao', '')
    orgao_f  = request.args.get('orgao', '')
    q        = request.args.get('q', '')

    query = Solicitacao.query
    if status_f: query = query.filter_by(status=status_f)
    if regiao_f: query = query.filter_by(regiao=regiao_f)
    if orgao_f:  query = query.filter_by(orgao=orgao_f)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Solicitacao.numero.like(like),
            Solicitacao.servidor_responsavel.like(like),
            Solicitacao.estado.like(like),
        ))
    items = query.order_by(Solicitacao.data_inicio.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Solicitações'

    hdr_font    = Font(bold=True, color='FFFFFF', size=11)
    hdr_fill    = PatternFill('solid', fgColor='1E3A5F')
    hdr_align   = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell_align  = Alignment(vertical='center', wrap_text=True)
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0'),
    )

    headers = [
        'Número', 'Status', 'Data Início', 'Data Fim', 'Duração (dias)',
        'Região', 'UF', 'Local de Início', 'Pernoite',
        'Órgão', 'Unidade / Secretaria',
        'Servidor Responsável', 'Contato',
        'Servidores Adicionais',
        'Tipo de Diária', 'Categoria do Veículo',
        'Qtd. Diárias', 'Valor Unitário (R$)', 'Valor Total (R$)',
        'Motorista', 'Tel. Motorista',
        'Observações',
    ]

    ws.row_dimensions[1].height = 30
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font      = hdr_font
        cell.fill      = hdr_fill
        cell.alignment = hdr_align

    for i, s in enumerate(items, 2):
        row_fill = PatternFill('solid', fgColor='F8FAFC') if i % 2 == 0 else None
        vals = [
            s.numero, s.status,
            s.data_inicio.strftime('%d/%m/%Y'), s.data_fim.strftime('%d/%m/%Y'),
            s.duracao_dias,
            s.regiao, s.estado, s.local_inicio or '',
            'Sim' if s.pernoite else 'Não',
            s.orgao, s.unidade_secretaria or '',
            s.servidor_responsavel or '', s.contato_responsavel or '',
            s.servidores_adicionais or '',
            s.tipo_diaria, s.categoria_veiculo,
            s.quantidade_diarias,
            float(s.valor_diaria or 0), float(s.valor_total),
            s.motorista_nome or '', s.motorista_telefone or '',
            s.observacoes or '',
        ]
        for col, v in enumerate(vals, 1):
            cell = ws.cell(row=i, column=col, value=v)
            cell.alignment = cell_align
            cell.border    = thin_border
            if row_fill: cell.fill = row_fill

    widths = [14, 16, 12, 12, 8, 14, 5, 24, 8, 6, 30, 26, 16, 26, 10, 18, 8, 12, 12, 22, 16, 30]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    ws.freeze_panes = 'A2'

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    fname = f'solicitacoes_{date.today().strftime("%Y%m%d")}.xlsx'
    return send_file(output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name=fname)


@app.route('/solicitacoes/nova', methods=['GET', 'POST'])
@login_required
def nova_solicitacao():
    motoristas = Motorista.query.filter_by(ativo=True).order_by(Motorista.nome).all()
    conflitos = []

    if request.method == 'POST':
        data_inicio = datetime.strptime(request.form['data_inicio'], '%Y-%m-%d').date()
        data_fim    = datetime.strptime(request.form['data_fim'], '%Y-%m-%d').date()
        servidor    = request.form.get('servidor_responsavel')

        conflitos = verificar_conflitos(servidor, data_inicio, data_fim)

        ultimo = Solicitacao.query.order_by(Solicitacao.id.desc()).first()
        seq    = (ultimo.id + 1) if ultimo else 1
        numero = f"SOL-{datetime.now().year}-{seq:04d}"

        sol = Solicitacao(
            numero=numero,
            data_inicio=data_inicio,
            data_fim=data_fim,
            local_inicio=request.form.get('local_inicio'),
            pernoite='pernoite' in request.form,
            regiao=request.form.get('regiao'),
            estado=request.form.get('estado'),
            servidor_responsavel=servidor,
            contato_responsavel=request.form.get('contato_responsavel'),
            servidores_adicionais=request.form.get('servidores_adicionais'),
            orgao=request.form.get('orgao'),
            unidade_secretaria=request.form.get('unidade_secretaria'),
            tipo_diaria=request.form.get('tipo_diaria'),
            categoria_veiculo=request.form.get('categoria_veiculo'),
            quantidade_diarias=int(request.form.get('quantidade_diarias') or 0),
            valor_diaria=float(request.form.get('valor_diaria') or 0),
            motorista_nome=request.form.get('motorista_nome'),
            motorista_telefone=request.form.get('motorista_telefone'),
            observacoes=request.form.get('observacoes'),
            status='Recebida',
            criado_por_id=current_user.id,
        )
        db.session.add(sol)
        db.session.flush()
        comprometer_saldo(sol)
        registrar_historico_status(sol, None, 'Recebida', 'Solicitação criada')
        db.session.commit()

        # Enviar email de recebimento se configurado
        try:
            from email_utils import send_email, email_recebimento_html, get_config
            email_gestor = get_config('email_notif_gestor', '')
            if email_gestor:
                send_email(app, email_gestor, f'Solicitação {numero} Recebida',
                           email_recebimento_html(sol))
        except Exception:
            pass

        if conflitos:
            flash(f'Solicitação <strong>{numero}</strong> criada. Atenção: {len(conflitos)} conflito(s) de período detectado(s).', 'warning')
        else:
            flash(f'Solicitação <strong>{numero}</strong> criada com sucesso!', 'success')
        return redirect(url_for('detalhe_solicitacao', id=sol.id))

    # Pré-preenchimento via query params (duplicação)
    pre = {k: request.args.get(k, '') for k in [
        'data_inicio', 'data_fim', 'local_inicio', 'regiao', 'estado',
        'servidor_responsavel', 'contato_responsavel', 'servidores_adicionais',
        'orgao', 'unidade_secretaria', 'tipo_diaria', 'categoria_veiculo',
        'quantidade_diarias', 'valor_diaria', 'motorista_nome',
        'motorista_telefone', 'observacoes', 'pernoite'
    ]}

    return render_template('solicitacoes/form.html',
        sol=None, regioes=REGIOES, estados=TODOS_ESTADOS,
        estados_por_regiao=ESTADOS_POR_REGIAO, tipos_diaria=TIPOS_DIARIA,
        categorias=CATEGORIAS, orgaos=ORGAOS, motoristas=motoristas,
        conflitos=conflitos, pre=pre)


@app.route('/solicitacoes/<int:id>')
@login_required
def detalhe_solicitacao(id):
    sol  = Solicitacao.query.get_or_404(id)
    prox = proximo_status(sol.status)
    return render_template('solicitacoes/detalhe.html',
        sol=sol, prox=prox, status_list=STATUS_WORKFLOW)


@app.route('/solicitacoes/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_solicitacao(id):
    sol = Solicitacao.query.get_or_404(id)
    motoristas = Motorista.query.filter_by(ativo=True).order_by(Motorista.nome).all()
    conflitos = []

    if request.method == 'POST':
        old_qty = sol.quantidade_diarias or 0

        data_inicio = datetime.strptime(request.form['data_inicio'], '%Y-%m-%d').date()
        data_fim    = datetime.strptime(request.form['data_fim'], '%Y-%m-%d').date()
        servidor    = request.form.get('servidor_responsavel')

        conflitos = verificar_conflitos(servidor, data_inicio, data_fim, excluir_id=sol.id)

        sol.data_inicio           = data_inicio
        sol.data_fim              = data_fim
        sol.local_inicio          = request.form.get('local_inicio')
        sol.pernoite              = 'pernoite' in request.form
        sol.regiao                = request.form.get('regiao')
        sol.estado                = request.form.get('estado')
        sol.servidor_responsavel  = servidor
        sol.contato_responsavel   = request.form.get('contato_responsavel')
        sol.servidores_adicionais = request.form.get('servidores_adicionais')
        sol.orgao                 = request.form.get('orgao')
        sol.unidade_secretaria    = request.form.get('unidade_secretaria')
        sol.tipo_diaria           = request.form.get('tipo_diaria')
        sol.categoria_veiculo     = request.form.get('categoria_veiculo')
        sol.quantidade_diarias    = int(request.form.get('quantidade_diarias') or 0)
        sol.valor_diaria          = float(request.form.get('valor_diaria') or 0)
        sol.motorista_nome        = request.form.get('motorista_nome')
        sol.motorista_telefone    = request.form.get('motorista_telefone')
        sol.observacoes           = request.form.get('observacoes')

        diff = sol.quantidade_diarias - old_qty
        if diff != 0 and sol.status not in ('Concluída', 'Cancelada'):
            saldo = get_saldo_ativo()
            if saldo:
                saldo.saldo_comprometido = max(0, saldo.saldo_comprometido + diff)

        db.session.commit()

        if conflitos:
            flash(f'Solicitação atualizada. Atenção: {len(conflitos)} conflito(s) de período detectado(s).', 'warning')
        else:
            flash('Solicitação atualizada!', 'success')
        return redirect(url_for('detalhe_solicitacao', id=sol.id))

    return render_template('solicitacoes/form.html',
        sol=sol, regioes=REGIOES, estados=TODOS_ESTADOS,
        estados_por_regiao=ESTADOS_POR_REGIAO, tipos_diaria=TIPOS_DIARIA,
        categorias=CATEGORIAS, orgaos=ORGAOS, motoristas=motoristas,
        conflitos=conflitos, pre={})


@app.route('/solicitacoes/<int:id>/avancar', methods=['POST'])
@login_required
def avancar_status(id):
    sol  = Solicitacao.query.get_or_404(id)
    prox = proximo_status(sol.status)
    if not prox:
        flash('Não há próximo status.', 'warning')
        return redirect(url_for('detalhe_solicitacao', id=id))

    if prox == 'Motorista Designado':
        sol.motorista_nome     = request.form.get('motorista_nome') or sol.motorista_nome
        sol.motorista_telefone = request.form.get('motorista_telefone') or sol.motorista_telefone

        # Enviar email quando motorista designado
        try:
            from email_utils import send_email, email_termo_html, get_config
            email_gestor = get_config('email_notif_gestor', '')
            if email_gestor:
                send_email(app, email_gestor,
                           f'Motorista Designado — {sol.numero}',
                           email_termo_html(sol))
        except Exception:
            pass

    atualizar_saldo_por_transicao(sol, prox)
    registrar_historico_status(sol, sol.status, prox)
    sol.status = prox
    db.session.commit()
    flash(f'Status atualizado para: <strong>{prox}</strong>', 'success')
    return redirect(url_for('detalhe_solicitacao', id=id))


@app.route('/solicitacoes/<int:id>/cancelar', methods=['POST'])
@login_required
def cancelar_solicitacao(id):
    sol = Solicitacao.query.get_or_404(id)
    if sol.status in ('Concluída', 'Cancelada'):
        flash('Esta solicitação não pode ser cancelada.', 'warning')
        return redirect(url_for('detalhe_solicitacao', id=id))

    motivo = request.form.get('motivo', '')
    atualizar_saldo_por_transicao(sol, 'Cancelada')
    registrar_historico_status(sol, sol.status, 'Cancelada', motivo)
    sol.status = 'Cancelada'
    if motivo:
        sol.observacoes = (sol.observacoes or '') + \
            f"\n[Cancelada em {datetime.now().strftime('%d/%m/%Y %H:%M')}] {motivo}"
    db.session.commit()
    flash('Solicitação cancelada.', 'warning')
    return redirect(url_for('detalhe_solicitacao', id=id))


@app.route('/solicitacoes/<int:id>/termo')
@login_required
def imprimir_termo(id):
    sol = Solicitacao.query.get_or_404(id)
    return render_template('solicitacoes/termo.html', sol=sol, hoje=date.today())


@app.route('/solicitacoes/<int:id>/comentar', methods=['POST'])
@login_required
def adicionar_comentario(id):
    sol   = Solicitacao.query.get_or_404(id)
    texto = request.form.get('texto', '').strip()
    if texto:
        c = Comentario(
            solicitacao_id=sol.id,
            usuario_id=current_user.id,
            texto=texto,
        )
        db.session.add(c)
        db.session.commit()
        flash('Comentário adicionado.', 'success')
    return redirect(url_for('detalhe_solicitacao', id=id))


@app.route('/solicitacoes/<int:id>/upload', methods=['POST'])
@login_required
def upload_anexo(id):
    sol = Solicitacao.query.get_or_404(id)
    f   = request.files.get('arquivo')
    if not f or f.filename == '':
        flash('Nenhum arquivo selecionado.', 'warning')
        return redirect(url_for('detalhe_solicitacao', id=id))

    if not allowed_file(f.filename):
        flash('Tipo de arquivo não permitido.', 'danger')
        return redirect(url_for('detalhe_solicitacao', id=id))

    pasta = os.path.join(app.config['UPLOAD_FOLDER'], str(id))
    os.makedirs(pasta, exist_ok=True)

    original  = f.filename
    safe_name = secure_filename(original)
    # Evitar colisão de nomes
    base, ext = os.path.splitext(safe_name)
    ts        = datetime.now().strftime('%Y%m%d%H%M%S')
    safe_name = f"{base}_{ts}{ext}"

    caminho = os.path.join(pasta, safe_name)
    f.save(caminho)
    tamanho = os.path.getsize(caminho)

    anexo = Anexo(
        solicitacao_id=sol.id,
        usuario_id=current_user.id,
        nome_original=original,
        nome_arquivo=safe_name,
        tipo_mime=f.content_type or 'application/octet-stream',
        tamanho_bytes=tamanho,
    )
    db.session.add(anexo)
    db.session.commit()
    flash('Arquivo anexado com sucesso.', 'success')
    return redirect(url_for('detalhe_solicitacao', id=id))


@app.route('/solicitacoes/<int:id>/anexo/<filename>')
@login_required
def baixar_anexo(id, filename):
    pasta = os.path.join(app.config['UPLOAD_FOLDER'], str(id))
    caminho = os.path.join(pasta, filename)
    if not os.path.exists(caminho):
        abort(404)
    return send_file(caminho, as_attachment=True, download_name=filename)


@app.route('/solicitacoes/<int:id>/anexo/<int:aid>/deletar', methods=['POST'])
@login_required
def deletar_anexo(id, aid):
    anexo = Anexo.query.get_or_404(aid)
    if anexo.solicitacao_id != id:
        abort(404)
    # Somente admin/gestor ou quem enviou pode deletar
    pode = (current_user.perfil in ('admin', 'gestor') or
            anexo.usuario_id == current_user.id)
    if not pode:
        flash('Sem permissão para remover este anexo.', 'danger')
        return redirect(url_for('detalhe_solicitacao', id=id))

    caminho = os.path.join(app.config['UPLOAD_FOLDER'], str(id), anexo.nome_arquivo)
    try:
        if os.path.exists(caminho):
            os.remove(caminho)
    except Exception:
        pass
    db.session.delete(anexo)
    db.session.commit()
    flash('Anexo removido.', 'success')
    return redirect(url_for('detalhe_solicitacao', id=id))


@app.route('/solicitacoes/<int:id>/duplicar')
@login_required
def duplicar_solicitacao(id):
    sol = Solicitacao.query.get_or_404(id)
    params = {
        'regiao': sol.regiao or '',
        'estado': sol.estado or '',
        'local_inicio': sol.local_inicio or '',
        'servidor_responsavel': sol.servidor_responsavel or '',
        'contato_responsavel': sol.contato_responsavel or '',
        'servidores_adicionais': sol.servidores_adicionais or '',
        'orgao': sol.orgao or '',
        'unidade_secretaria': sol.unidade_secretaria or '',
        'tipo_diaria': sol.tipo_diaria or '',
        'categoria_veiculo': sol.categoria_veiculo or '',
        'quantidade_diarias': sol.quantidade_diarias or 0,
        'valor_diaria': float(sol.valor_diaria or 0),
        'motorista_nome': sol.motorista_nome or '',
        'motorista_telefone': sol.motorista_telefone or '',
        'observacoes': sol.observacoes or '',
        'pernoite': '1' if sol.pernoite else '',
    }
    return redirect(url_for('nova_solicitacao', **params))


@app.route('/solicitacoes/<int:id>/aceite', methods=['POST'])
@login_required
def registrar_aceite(id):
    sol = Solicitacao.query.get_or_404(id)
    sol.aceite_eletronico = True
    sol.aceite_data       = datetime.now()
    registrar_historico_status(sol, sol.status, sol.status, 'Aceite Eletrônico registrado')
    db.session.commit()
    flash('Aceite eletrônico registrado com sucesso.', 'success')
    return redirect(url_for('detalhe_solicitacao', id=id))


# ── API motoristas ─────────────────────────────────────────────────────────────

@app.route('/api/motoristas')
@login_required
def api_motoristas():
    q = request.args.get('q', '').strip()
    query = Motorista.query.filter_by(ativo=True)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Motorista.nome.like(like),
            Motorista.empresa.like(like),
        ))
    mots = query.order_by(Motorista.nome).limit(20).all()
    return jsonify([{
        'id':       m.id,
        'nome':     m.nome,
        'telefone': m.telefone or '',
        'empresa':  m.empresa or '',
    } for m in mots])


# ── Importar solicitações ──────────────────────────────────────────────────────

@app.route('/solicitacoes/importar', methods=['GET', 'POST'])
@login_required
def importar_solicitacoes():
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'template':
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Importação'
            colunas = [
                'data_inicio', 'data_fim', 'regiao', 'estado', 'local_inicio',
                'pernoite', 'orgao', 'unidade_secretaria', 'servidor_responsavel',
                'contato_responsavel', 'servidores_adicionais', 'tipo_diaria',
                'categoria_veiculo', 'quantidade_diarias', 'valor_diaria',
                'motorista_nome', 'motorista_telefone', 'observacoes'
            ]
            ws.append(colunas)
            # Linha de exemplo
            ws.append([
                '01/04/2026', '03/04/2026', 'Nordeste', 'CE', 'Aeroporto de Fortaleza',
                'Sim', 'MDS', 'SNAS', 'João da Silva', '(61) 99999-9999',
                '', '10h', 'Sedan Popular', 2, 250.00,
                'Carlos Motorista', '(61) 88888-8888', 'Observação exemplo'
            ])
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            return send_file(output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True, download_name='modelo_importacao.xlsx')

        elif action == 'preview':
            f = request.files.get('arquivo')
            if not f:
                flash('Nenhum arquivo enviado.', 'warning')
                return redirect(url_for('importar_solicitacoes'))
            try:
                import openpyxl
                wb = openpyxl.load_workbook(f)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    flash('Planilha vazia.', 'warning')
                    return redirect(url_for('importar_solicitacoes'))
                headers = [str(h).strip() if h else '' for h in rows[0]]
                preview = []
                for i, row in enumerate(rows[1:], 2):
                    item = dict(zip(headers, row))
                    item['_linha'] = i
                    item['_erro'] = ''
                    # Validações básicas
                    if not item.get('data_inicio') or not item.get('data_fim'):
                        item['_erro'] = 'Datas obrigatórias'
                    if not item.get('servidor_responsavel'):
                        item['_erro'] = (item['_erro'] + '; ' if item['_erro'] else '') + 'Servidor obrigatório'
                    preview.append(item)
                session['import_preview'] = preview
                session['import_headers'] = headers
                return render_template('solicitacoes/importar.html',
                    step='preview', preview=preview, headers=headers)
            except Exception as e:
                flash(f'Erro ao processar arquivo: {e}', 'danger')
                return redirect(url_for('importar_solicitacoes'))

        elif action == 'confirmar':
            preview = session.get('import_preview', [])
            selecionados = request.form.getlist('selecionar')
            criados = 0
            for item in preview:
                if str(item['_linha']) not in selecionados:
                    continue
                if item['_erro']:
                    continue
                try:
                    def parse_date(val):
                        if not val:
                            return None
                        if hasattr(val, 'date'):
                            return val.date()
                        for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
                            try:
                                return datetime.strptime(str(val), fmt).date()
                            except Exception:
                                pass
                        return None

                    di = parse_date(item.get('data_inicio'))
                    df = parse_date(item.get('data_fim'))
                    if not di or not df:
                        continue

                    ultimo = Solicitacao.query.order_by(Solicitacao.id.desc()).first()
                    seq    = (ultimo.id + 1) if ultimo else 1
                    numero = f"SOL-{datetime.now().year}-{seq:04d}"

                    sol = Solicitacao(
                        numero=numero,
                        data_inicio=di,
                        data_fim=df,
                        local_inicio=str(item.get('local_inicio') or ''),
                        pernoite=str(item.get('pernoite', '')).lower() in ('sim', 'true', '1', 's'),
                        regiao=str(item.get('regiao') or ''),
                        estado=str(item.get('estado') or ''),
                        servidor_responsavel=str(item.get('servidor_responsavel') or ''),
                        contato_responsavel=str(item.get('contato_responsavel') or ''),
                        servidores_adicionais=str(item.get('servidores_adicionais') or ''),
                        orgao=str(item.get('orgao') or 'MDS'),
                        unidade_secretaria=str(item.get('unidade_secretaria') or ''),
                        tipo_diaria=str(item.get('tipo_diaria') or 'Transporte'),
                        categoria_veiculo=str(item.get('categoria_veiculo') or 'Sedan Popular'),
                        quantidade_diarias=int(item.get('quantidade_diarias') or 0),
                        valor_diaria=float(item.get('valor_diaria') or 0),
                        motorista_nome=str(item.get('motorista_nome') or ''),
                        motorista_telefone=str(item.get('motorista_telefone') or ''),
                        observacoes=str(item.get('observacoes') or ''),
                        status='Recebida',
                        criado_por_id=current_user.id,
                    )
                    db.session.add(sol)
                    db.session.flush()
                    comprometer_saldo(sol)
                    registrar_historico_status(sol, None, 'Recebida', 'Importação em lote')
                    db.session.commit()
                    criados += 1
                except Exception:
                    db.session.rollback()

            session.pop('import_preview', None)
            flash(f'{criados} solicitação(ões) importada(s) com sucesso.', 'success')
            return redirect(url_for('lista_solicitacoes'))

    return render_template('solicitacoes/importar.html', step='upload', preview=[], headers=[])


# ── Relatório de conformidade ──────────────────────────────────────────────────

@app.route('/relatorios/conformidade')
@login_required
def relatorio_conformidade():
    hoje_d = date.today()
    status_conclusivos = ['Concluída', 'Cancelada']

    # Serviços vencidos
    vencidos = Solicitacao.query.filter(
        Solicitacao.data_fim < hoje_d,
        Solicitacao.status.notin_(status_conclusivos)
    ).order_by(Solicitacao.data_fim).all()

    # Conflitos de período (servidor com 2+ solicitações sobrepostas)
    ativos = Solicitacao.query.filter(
        Solicitacao.status.notin_(status_conclusivos)
    ).all()

    conflitos_dict = {}
    for i, s1 in enumerate(ativos):
        if not s1.servidor_responsavel:
            continue
        for s2 in ativos[i+1:]:
            if s1.servidor_responsavel != s2.servidor_responsavel:
                continue
            if s1.data_inicio <= s2.data_fim and s1.data_fim >= s2.data_inicio:
                chave = s1.servidor_responsavel
                if chave not in conflitos_dict:
                    conflitos_dict[chave] = set()
                conflitos_dict[chave].add(s1.id)
                conflitos_dict[chave].add(s2.id)

    conflitos = {}
    for servidor, ids in conflitos_dict.items():
        conflitos[servidor] = [Solicitacao.query.get(i) for i in ids]

    # Sem motorista mas status >= Motorista Designado
    idx_mot = STATUS_WORKFLOW.index('Motorista Designado')
    status_com_motorista = STATUS_WORKFLOW[idx_mot:]
    sem_motorista = Solicitacao.query.filter(
        Solicitacao.status.in_(status_com_motorista),
        db.or_(
            Solicitacao.motorista_nome == None,
            Solicitacao.motorista_nome == '',
        )
    ).all()

    # Cancelados nos últimos 30 dias
    trinta_dias_atras = datetime.now() - timedelta(days=30)
    cancelados_recentes = Solicitacao.query.filter(
        Solicitacao.status == 'Cancelada',
        Solicitacao.data_criacao >= trinta_dias_atras,
    ).order_by(Solicitacao.data_criacao.desc()).all()

    total_problemas = len(vencidos) + len(conflitos) + len(sem_motorista)

    return render_template('relatorios/conformidade.html',
        vencidos=vencidos,
        conflitos=conflitos,
        sem_motorista=sem_motorista,
        cancelados_recentes=cancelados_recentes,
        total_problemas=total_problemas,
        hoje=hoje_d,
    )


# ── Usuários ───────────────────────────────────────────────────────────────────

@app.route('/usuarios')
@login_required
@requer_perfil('admin')
def lista_usuarios():
    users = Usuario.query.order_by(Usuario.nome).all()
    return render_template('usuarios/lista.html', users=users)


@app.route('/usuarios/novo', methods=['GET', 'POST'])
@login_required
@requer_perfil('admin')
def novo_usuario():
    if request.method == 'POST':
        matricula = request.form.get('matricula', '').strip()
        if Usuario.query.filter_by(matricula=matricula).first():
            flash('Matrícula já cadastrada.', 'danger')
            return render_template('usuarios/form.html', u=None)

        u = Usuario(
            nome=request.form.get('nome'),
            matricula=matricula,
            email=request.form.get('email'),
            perfil=request.form.get('perfil', 'operador'),
        )
        senha = request.form.get('senha', '')
        if not senha:
            flash('Senha é obrigatória para novo usuário.', 'danger')
            return render_template('usuarios/form.html', u=None)
        u.set_senha(senha)
        db.session.add(u)
        db.session.commit()
        flash(f'Usuário <strong>{u.nome}</strong> criado com sucesso!', 'success')
        return redirect(url_for('lista_usuarios'))
    return render_template('usuarios/form.html', u=None)


@app.route('/usuarios/<int:id>', methods=['GET', 'POST'])
@login_required
@requer_perfil('admin')
def editar_usuario(id):
    u = Usuario.query.get_or_404(id)
    if request.method == 'POST':
        u.nome   = request.form.get('nome')
        u.email  = request.form.get('email')
        u.perfil = request.form.get('perfil', 'operador')
        u.ativo  = 'ativo' in request.form

        nova_matricula = request.form.get('matricula', '').strip()
        if nova_matricula != u.matricula:
            if Usuario.query.filter_by(matricula=nova_matricula).first():
                flash('Matrícula já cadastrada para outro usuário.', 'danger')
                return render_template('usuarios/form.html', u=u)
            u.matricula = nova_matricula

        senha = request.form.get('senha', '')
        if senha:
            u.set_senha(senha)

        db.session.commit()
        flash('Usuário atualizado!', 'success')
        return redirect(url_for('lista_usuarios'))
    return render_template('usuarios/form.html', u=u)


# ── Configurações ──────────────────────────────────────────────────────────────

@app.route('/configuracoes', methods=['GET', 'POST'])
@login_required
@requer_perfil('admin')
def configuracoes():
    if request.method == 'POST':
        chaves = ['smtp_server', 'smtp_port', 'smtp_user', 'smtp_pass',
                  'smtp_from', 'email_notif_gestor']
        for chave in chaves:
            valor = request.form.get(chave, '')
            cfg = Configuracao.query.get(chave)
            if cfg:
                cfg.valor = valor
            else:
                db.session.add(Configuracao(chave=chave, valor=valor))
        db.session.commit()

        # Testar envio se solicitado
        if request.form.get('testar'):
            try:
                from email_utils import send_email
                dest = request.form.get('email_notif_gestor', '')
                if dest:
                    ok = send_email(app, dest, 'Teste de Configuração SMTP',
                                    '<p>Configuração de e-mail funcionando corretamente.</p>')
                    if ok:
                        flash('E-mail de teste enviado com sucesso!', 'success')
                    else:
                        flash('Falha ao enviar e-mail de teste. Verifique as configurações.', 'danger')
                else:
                    flash('Configure o e-mail do gestor para testar.', 'warning')
            except Exception as e:
                flash(f'Erro: {e}', 'danger')
        else:
            flash('Configurações salvas!', 'success')
        return redirect(url_for('configuracoes'))

    cfgs = {c.chave: c.valor for c in Configuracao.query.all()}
    total_sols   = Solicitacao.query.count()
    total_mots   = Motorista.query.count()
    total_users  = Usuario.query.count()
    return render_template('configuracoes.html',
        cfgs=cfgs, total_sols=total_sols,
        total_mots=total_mots, total_users=total_users)


# ── Saldo ─────────────────────────────────────────────────────────────────────

@app.route('/saldo', methods=['GET', 'POST'])
@login_required
def saldo():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'criar':
            item = SaldoDiarias(
                descricao=request.form.get('descricao'),
                saldo_total=int(request.form.get('saldo_total') or 0),
                valor_referencia=float(request.form.get('valor_referencia') or 0),
            )
            db.session.add(item)
            db.session.commit()
            flash('Saldo criado!', 'success')
        elif action == 'creditar':
            item = SaldoDiarias.query.get_or_404(int(request.form.get('saldo_id')))
            qty  = int(request.form.get('quantidade') or 0)
            item.saldo_total += qty
            db.session.add(HistoricoSaldo(
                tipo='Crédito', quantidade=qty,
                valor=qty * float(item.valor_referencia or 0),
                descricao=request.form.get('descricao_mov') or f'Crédito de {qty} diárias',
                saldo_id=item.id,
            ))
            db.session.commit()
            flash(f'{qty} diárias creditadas!', 'success')
        elif action == 'toggle':
            item = SaldoDiarias.query.get_or_404(int(request.form.get('saldo_id')))
            item.ativo = not item.ativo
            db.session.commit()
        return redirect(url_for('saldo'))

    saldos    = SaldoDiarias.query.order_by(SaldoDiarias.data_atualizacao.desc()).all()
    historico = HistoricoSaldo.query.order_by(HistoricoSaldo.data.desc()).limit(30).all()
    return render_template('saldo/index.html', saldos=saldos, historico=historico)


# ── Motoristas ────────────────────────────────────────────────────────────────

@app.route('/motoristas')
@login_required
def lista_motoristas():
    q     = request.args.get('q', '')
    query = Motorista.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Motorista.nome.like(like),
            Motorista.empresa.like(like),
            Motorista.telefone.like(like),
        ))
    motoristas = query.order_by(Motorista.nome).all()
    return render_template('motoristas/lista.html', motoristas=motoristas, q=q)


@app.route('/motoristas/novo', methods=['GET', 'POST'])
@login_required
def novo_motorista():
    if request.method == 'POST':
        m = Motorista(
            nome=request.form.get('nome'),
            telefone=request.form.get('telefone'),
            empresa=request.form.get('empresa'),
            observacoes=request.form.get('observacoes'),
        )
        db.session.add(m)
        db.session.commit()
        flash(f'Motorista <strong>{m.nome}</strong> cadastrado!', 'success')
        return redirect(url_for('detalhe_motorista', id=m.id))
    return render_template('motoristas/form.html', m=None)


@app.route('/motoristas/<int:id>', methods=['GET', 'POST'])
@login_required
def detalhe_motorista(id):
    m = Motorista.query.get_or_404(id)
    if request.method == 'POST':
        m.nome        = request.form.get('nome')
        m.telefone    = request.form.get('telefone')
        m.empresa     = request.form.get('empresa')
        m.observacoes = request.form.get('observacoes')
        m.ativo       = 'ativo' in request.form
        db.session.commit()
        flash('Dados do motorista atualizados!', 'success')
        return redirect(url_for('detalhe_motorista', id=id))

    viagens = (Solicitacao.query
               .filter(Solicitacao.motorista_nome.ilike(f'%{m.nome}%'))
               .order_by(Solicitacao.data_inicio.desc()).all())
    return render_template('motoristas/detalhe.html', m=m, viagens=viagens)


# ── Calendário ────────────────────────────────────────────────────────────────

@app.route('/calendario')
@login_required
def calendario():
    hoje_d = date.today()
    year   = int(request.args.get('year',  hoje_d.year))
    month  = int(request.args.get('month', hoje_d.month))

    first  = date(year, month, 1)
    last   = date(year, month, monthrange(year, month)[1])

    servicos = (Solicitacao.query
                .filter(
                    Solicitacao.data_inicio <= last,
                    Solicitacao.data_fim >= first,
                    Solicitacao.status.notin_(['Cancelada'])
                ).order_by(Solicitacao.data_inicio).all())

    start = first - timedelta(days=first.weekday())
    weeks = []
    cur   = start
    while cur <= last or len(weeks) < 5:
        week = []
        for _ in range(7):
            day_s = [s for s in servicos if s.data_inicio <= cur <= s.data_fim]
            week.append({'date': cur, 'in_month': cur.month == month,
                         'today': cur == hoje_d, 'services': day_s})
            cur += timedelta(days=1)
        weeks.append(week)
        if cur > last and len(weeks) >= 4:
            break

    prev = (first - timedelta(days=1)).replace(day=1)
    nxt  = (last  + timedelta(days=1))

    return render_template('calendario.html',
        weeks=weeks, year=year, month=month,
        month_name=f"{MESES_PT[month]} {year}",
        prev_year=prev.year, prev_month=prev.month,
        next_year=nxt.year,  next_month=nxt.month,
        cores_regiao=CORES_REGIAO, regioes=REGIOES)


# ── Relatórios ────────────────────────────────────────────────────────────────

@app.route('/relatorios')
@login_required
def relatorios():
    from sqlalchemy import extract, func

    hoje_d = date.today()

    meses = []
    y, m  = hoje_d.year, hoje_d.month
    for _ in range(12):
        meses.append((y, m))
        m -= 1
        if m == 0: m = 12; y -= 1
    meses.reverse()

    monthly_sols    = []
    monthly_diarias = []
    monthly_labels  = []
    for y, m in meses:
        cnt = Solicitacao.query.filter(
            extract('year',  Solicitacao.data_inicio) == y,
            extract('month', Solicitacao.data_inicio) == m,
        ).count()
        d = db.session.query(func.sum(Solicitacao.quantidade_diarias)).filter(
            extract('year',  Solicitacao.data_inicio) == y,
            extract('month', Solicitacao.data_inicio) == m,
            Solicitacao.status == 'Concluída',
        ).scalar() or 0
        monthly_sols.append(cnt)
        monthly_diarias.append(int(d))
        monthly_labels.append(f"{m:02d}/{str(y)[2:]}")

    by_regiao = db.session.query(
        Solicitacao.regiao,
        func.count(Solicitacao.id).label('total'),
        func.sum(Solicitacao.quantidade_diarias).label('diarias')
    ).group_by(Solicitacao.regiao).all()

    by_status = db.session.query(
        Solicitacao.status,
        func.count(Solicitacao.id).label('total')
    ).group_by(Solicitacao.status).all()

    by_cat = db.session.query(
        Solicitacao.categoria_veiculo,
        func.count(Solicitacao.id).label('total'),
        func.sum(Solicitacao.quantidade_diarias).label('diarias')
    ).filter(Solicitacao.categoria_veiculo != None).group_by(Solicitacao.categoria_veiculo).all()

    top_serv = db.session.query(
        Solicitacao.servidor_responsavel,
        func.count(Solicitacao.id).label('total'),
        func.sum(Solicitacao.quantidade_diarias).label('diarias')
    ).filter(Solicitacao.servidor_responsavel != None) \
     .group_by(Solicitacao.servidor_responsavel) \
     .order_by(func.count(Solicitacao.id).desc()).limit(10).all()

    saldo = get_saldo_ativo()

    return render_template('relatorios.html',
        monthly_labels=monthly_labels,
        monthly_sols=monthly_sols,
        monthly_diarias=monthly_diarias,
        by_regiao=by_regiao,
        by_status=by_status,
        by_cat=by_cat,
        top_serv=top_serv,
        saldo=saldo,
        cores_regiao=CORES_REGIAO,
        total=Solicitacao.query.count(),
        total_ativas=Solicitacao.query.filter(
            Solicitacao.status.notin_(['Concluída','Cancelada'])).count(),
        total_concluidas=Solicitacao.query.filter_by(status='Concluída').count(),
        total_canceladas=Solicitacao.query.filter_by(status='Cancelada').count(),
    )


# ── Busca global ──────────────────────────────────────────────────────────────

@app.route('/buscar')
@login_required
def buscar():
    q = request.args.get('q', '').strip()
    sols = []
    mots = []
    if q:
        like = f'%{q}%'
        sols = (Solicitacao.query.filter(db.or_(
            Solicitacao.numero.like(like),
            Solicitacao.servidor_responsavel.like(like),
            Solicitacao.estado.like(like),
            Solicitacao.motorista_nome.like(like),
            Solicitacao.unidade_secretaria.like(like),
            Solicitacao.orgao.like(like),
        )).order_by(Solicitacao.data_criacao.desc()).limit(20).all())

        mots = (Motorista.query.filter(db.or_(
            Motorista.nome.like(like),
            Motorista.telefone.like(like),
            Motorista.empresa.like(like),
        )).limit(10).all())

    return render_template('busca.html', q=q, sols=sols, mots=mots)


# ── Context processor ─────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    return dict(
        hoje=date.today(),
        STATUS_WORKFLOW=STATUS_WORKFLOW,
        saldo_sidebar=get_saldo_ativo(),
        current_user=current_user,
    )


# ── Bootstrap ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        migrate_db()

        # Criar admin padrão se não existir
        if not Usuario.query.filter_by(matricula='admin').first():
            admin = Usuario(
                matricula='admin',
                nome='Administrador',
                perfil='admin',
                email='',
            )
            admin.set_senha('admin123')
            db.session.add(admin)
            db.session.commit()
            print('Admin padrão criado: admin / admin123')

        # Criar pasta uploads
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    app.run(debug=True, port=5000, host='0.0.0.0')
