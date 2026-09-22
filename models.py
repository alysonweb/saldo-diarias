from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

STATUS_WORKFLOW = [
    'Recebida',
    'Encaminhada',
    'Motorista Designado',
    'Termo Enviado',
    'Confirmada',
    'Em Execução',
    'Concluída',
]

STATUS_CORES = {
    'Recebida':            'secondary',
    'Encaminhada':         'info',
    'Motorista Designado': 'primary',
    'Termo Enviado':       'warning',
    'Confirmada':          'success',
    'Em Execução':         'danger',
    'Concluída':           'dark',
    'Cancelada':           'light',
}

REGIOES = ['Norte', 'Nordeste', 'Centro-Oeste', 'Sudeste', 'Sul']

CORES_REGIAO = {
    'Norte':        '#0891b2',
    'Nordeste':     '#7c3aed',
    'Centro-Oeste': '#059669',
    'Sudeste':      '#dc2626',
    'Sul':          '#d97706',
}

ESTADOS_POR_REGIAO = {
    'Norte':        ['AC', 'AM', 'AP', 'PA', 'RO', 'RR', 'TO'],
    'Nordeste':     ['AL', 'BA', 'CE', 'MA', 'PB', 'PE', 'PI', 'RN', 'SE'],
    'Centro-Oeste': ['DF', 'GO', 'MS', 'MT'],
    'Sudeste':      ['ES', 'MG', 'RJ', 'SP'],
    'Sul':          ['PR', 'RS', 'SC'],
}

TIPOS_DIARIA = ['Transporte', '10h', '24h']
CATEGORIAS   = ['Sedan Popular', 'Sedan Executivo', 'Camionete', 'Van', 'Blindado']
ORGAOS       = ['MDS', 'MESP']


# ── Usuário ────────────────────────────────────────────────────────────────────

class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'

    id            = db.Column(db.Integer, primary_key=True)
    nome          = db.Column(db.String(200), nullable=False)
    matricula     = db.Column(db.String(50), unique=True, nullable=False)
    email         = db.Column(db.String(200))
    senha_hash    = db.Column(db.String(256))
    perfil        = db.Column(db.String(20), default='operador')  # admin/gestor/operador
    ativo         = db.Column(db.Boolean, default=True)
    ultimo_acesso = db.Column(db.DateTime)
    data_criacao  = db.Column(db.DateTime, default=datetime.now)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

    @property
    def perfil_label(self):
        labels = {'admin': 'Administrador', 'gestor': 'Gestor', 'operador': 'Operador'}
        return labels.get(self.perfil, self.perfil)


# ── Comentário ─────────────────────────────────────────────────────────────────

class Comentario(db.Model):
    __tablename__ = 'comentarios'

    id             = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)
    usuario_id     = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    texto          = db.Column(db.Text, nullable=False)
    data           = db.Column(db.DateTime, default=datetime.now)

    usuario = db.relationship('Usuario', foreign_keys=[usuario_id])


# ── Anexo ──────────────────────────────────────────────────────────────────────

class Anexo(db.Model):
    __tablename__ = 'anexos'

    id             = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)
    usuario_id     = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    nome_original  = db.Column(db.String(300))
    nome_arquivo   = db.Column(db.String(300))
    tipo_mime      = db.Column(db.String(100))
    tamanho_bytes  = db.Column(db.Integer, default=0)
    data           = db.Column(db.DateTime, default=datetime.now)

    usuario = db.relationship('Usuario', foreign_keys=[usuario_id])

    @property
    def icone_tipo(self):
        mime = (self.tipo_mime or '').lower()
        if 'pdf' in mime:
            return 'fa-file-pdf'
        elif 'word' in mime or 'document' in mime or 'docx' in mime or 'doc' in mime:
            return 'fa-file-word'
        elif 'excel' in mime or 'spreadsheet' in mime or 'xlsx' in mime or 'xls' in mime:
            return 'fa-file-excel'
        elif 'image' in mime or 'png' in mime or 'jpg' in mime or 'jpeg' in mime or 'gif' in mime:
            return 'fa-file-image'
        else:
            return 'fa-file-alt'


# ── Configuração ───────────────────────────────────────────────────────────────

class Configuracao(db.Model):
    __tablename__ = 'configuracoes'

    chave = db.Column(db.String(100), primary_key=True)
    valor = db.Column(db.Text)


# ── Motorista ──────────────────────────────────────────────────────────────────

class Motorista(db.Model):
    __tablename__ = 'motoristas'

    id            = db.Column(db.Integer, primary_key=True)
    nome          = db.Column(db.String(200), nullable=False)
    telefone      = db.Column(db.String(50))
    empresa       = db.Column(db.String(200))
    observacoes   = db.Column(db.Text)
    ativo         = db.Column(db.Boolean, default=True)
    data_cadastro = db.Column(db.DateTime, default=datetime.now)

    @property
    def total_viagens(self):
        return Solicitacao.query.filter(
            Solicitacao.motorista_nome.ilike(f'%{self.nome}%')
        ).count()


# ── Solicitação ────────────────────────────────────────────────────────────────

class Solicitacao(db.Model):
    __tablename__ = 'solicitacoes'

    id                    = db.Column(db.Integer, primary_key=True)
    numero                = db.Column(db.String(20), unique=True, nullable=False)
    data_criacao          = db.Column(db.DateTime, default=datetime.now)

    data_inicio           = db.Column(db.Date, nullable=False)
    data_fim              = db.Column(db.Date, nullable=False)
    local_inicio          = db.Column(db.String(200))
    pernoite              = db.Column(db.Boolean, default=False)

    regiao                = db.Column(db.String(50))
    estado                = db.Column(db.String(2))

    servidor_responsavel  = db.Column(db.String(200))
    contato_responsavel   = db.Column(db.String(50))
    servidores_adicionais = db.Column(db.Text)

    orgao                 = db.Column(db.String(10))
    unidade_secretaria    = db.Column(db.String(200))

    tipo_diaria           = db.Column(db.String(20))
    categoria_veiculo     = db.Column(db.String(50))
    quantidade_diarias    = db.Column(db.Integer, default=0)
    valor_diaria          = db.Column(db.Numeric(10, 2), default=0)

    motorista_nome        = db.Column(db.String(200))
    motorista_telefone    = db.Column(db.String(50))

    status                = db.Column(db.String(30), default='Recebida')
    observacoes           = db.Column(db.Text)

    # Novos campos
    criado_por_id         = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    aceite_eletronico     = db.Column(db.Boolean, default=False)
    aceite_data           = db.Column(db.DateTime, nullable=True)

    historico_status = db.relationship(
        'HistoricoStatus', backref='solicitacao_ref', lazy=True,
        order_by='HistoricoStatus.data.asc()',
        foreign_keys='HistoricoStatus.solicitacao_id'
    )

    comentarios = db.relationship(
        'Comentario', backref='solicitacao', lazy=True,
        order_by='Comentario.data.asc()',
        foreign_keys='Comentario.solicitacao_id'
    )

    anexos = db.relationship(
        'Anexo', backref='solicitacao', lazy=True,
        order_by='Anexo.data.asc()',
        foreign_keys='Anexo.solicitacao_id'
    )

    criado_por = db.relationship('Usuario', foreign_keys=[criado_por_id])

    @property
    def valor_total(self):
        return (self.quantidade_diarias or 0) * float(self.valor_diaria or 0)

    @property
    def duracao_dias(self):
        if self.data_inicio and self.data_fim:
            return (self.data_fim - self.data_inicio).days + 1
        return 0

    @property
    def cor_status(self):
        return STATUS_CORES.get(self.status, 'secondary')

    @property
    def ativo(self):
        return self.status not in ('Concluída', 'Cancelada')


class HistoricoStatus(db.Model):
    __tablename__ = 'historico_status'

    id              = db.Column(db.Integer, primary_key=True)
    solicitacao_id  = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)
    status_anterior = db.Column(db.String(30))
    status_novo     = db.Column(db.String(30), nullable=False)
    data            = db.Column(db.DateTime, default=datetime.now)
    observacao      = db.Column(db.String(500))


class SaldoDiarias(db.Model):
    __tablename__ = 'saldo_diarias'

    id                 = db.Column(db.Integer, primary_key=True)
    descricao          = db.Column(db.String(200))
    saldo_total        = db.Column(db.Integer, default=0)
    saldo_usado        = db.Column(db.Integer, default=0)
    saldo_comprometido = db.Column(db.Integer, default=0)
    valor_referencia   = db.Column(db.Numeric(10, 2), default=0)
    data_atualizacao   = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    ativo              = db.Column(db.Boolean, default=True)

    historico = db.relationship('HistoricoSaldo', backref='saldo', lazy=True,
                                order_by='HistoricoSaldo.data.desc()')

    @property
    def saldo_livre(self):
        return self.saldo_total - self.saldo_usado - self.saldo_comprometido

    @property
    def pct_usado(self):
        if self.saldo_total == 0:
            return 0
        return round((self.saldo_usado / self.saldo_total) * 100)

    @property
    def pct_comprometido(self):
        if self.saldo_total == 0:
            return 0
        return round((self.saldo_comprometido / self.saldo_total) * 100)


class HistoricoSaldo(db.Model):
    __tablename__ = 'historico_saldo'

    id             = db.Column(db.Integer, primary_key=True)
    data           = db.Column(db.DateTime, default=datetime.now)
    tipo           = db.Column(db.String(20))
    quantidade     = db.Column(db.Integer)
    valor          = db.Column(db.Numeric(10, 2))
    descricao      = db.Column(db.String(500))
    saldo_id       = db.Column(db.Integer, db.ForeignKey('saldo_diarias.id'))
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=True)

    solicitacao = db.relationship('Solicitacao', foreign_keys=[solicitacao_id])
