from flask_mail import Mail, Message


def get_config(chave, default=''):
    try:
        from models import Configuracao
        cfg = Configuracao.query.get(chave)
        return cfg.valor if cfg and cfg.valor is not None else default
    except Exception:
        return default


def send_email(app, to, subject, html_body):
    smtp_server = get_config('smtp_server', '')
    if not smtp_server:
        return False

    smtp_port   = int(get_config('smtp_port', '587') or '587')
    smtp_user   = get_config('smtp_user', '')
    smtp_pass   = get_config('smtp_pass', '')
    smtp_from   = get_config('smtp_from', smtp_user)

    try:
        app.config['MAIL_SERVER']   = smtp_server
        app.config['MAIL_PORT']     = smtp_port
        app.config['MAIL_USERNAME'] = smtp_user
        app.config['MAIL_PASSWORD'] = smtp_pass
        app.config['MAIL_DEFAULT_SENDER'] = smtp_from
        app.config['MAIL_USE_TLS']  = smtp_port == 587
        app.config['MAIL_USE_SSL']  = smtp_port == 465

        mail = Mail(app)
        with app.app_context():
            msg = Message(subject=subject, recipients=[to], html=html_body)
            mail.send(msg)
        return True
    except Exception:
        return False


def email_recebimento_html(sol):
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:#0d1b2e;padding:20px 30px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;font-size:18px;">DITRAN / MDS</h2>
        <p style="color:#94a3b8;margin:4px 0 0;font-size:13px;">Sistema de Controle de Diárias</p>
      </div>
      <div style="background:#fff;padding:30px;border:1px solid #e2e8f0;border-top:none;">
        <h3 style="color:#0d1b2e;margin-top:0;">Solicitação Recebida</h3>
        <p>Prezados,</p>
        <p>Informamos que a solicitação <strong>{sol.numero}</strong> foi devidamente recebida e está em tratamento.</p>
        <div style="background:#f0f4f8;border-radius:8px;padding:16px;margin:20px 0;">
          <p style="margin:0 0 8px;font-size:13px;"><strong>Número:</strong> {sol.numero}</p>
          <p style="margin:0 0 8px;font-size:13px;"><strong>Período:</strong> {sol.data_inicio.strftime('%d/%m/%Y')} a {sol.data_fim.strftime('%d/%m/%Y')}</p>
          <p style="margin:0 0 8px;font-size:13px;"><strong>Servidor:</strong> {sol.servidor_responsavel or '-'}</p>
          <p style="margin:0;font-size:13px;"><strong>Destino:</strong> {sol.estado} — {sol.regiao}</p>
        </div>
        <p>Assim que tivermos o contato do motorista designado, repassaremos as informações necessárias.</p>
        <p>Atenciosamente,<br><strong>DITRAN/MDS</strong></p>
      </div>
      <div style="background:#f8fafc;padding:12px 30px;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 8px 8px;">
        <p style="margin:0;font-size:11px;color:#94a3b8;">Este é um e-mail automático do Sistema de Controle de Diárias — MDS/DITRAN.</p>
      </div>
    </div>
    """


def email_termo_html(sol):
    motorista_info = ''
    if sol.motorista_nome:
        motorista_info = f"<p style='margin:0 0 8px;font-size:13px;'><strong>Motorista:</strong> {sol.motorista_nome}"
        if sol.motorista_telefone:
            motorista_info += f" — {sol.motorista_telefone}"
        motorista_info += "</p>"

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:#0d1b2e;padding:20px 30px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;font-size:18px;">DITRAN / MDS</h2>
        <p style="color:#94a3b8;margin:4px 0 0;font-size:13px;">Termo de Notificação</p>
      </div>
      <div style="background:#fff;padding:30px;border:1px solid #e2e8f0;border-top:none;">
        <h3 style="color:#0d1b2e;margin-top:0;">Termo de Notificação — {sol.numero}</h3>
        <p>Prezado(a) <strong>{sol.servidor_responsavel or '[SERVIDOR]'}</strong>,</p>
        <p>Em cumprimento às normas vigentes, informamos as condições do serviço autorizado:</p>
        <div style="background:#f0f4f8;border-radius:8px;padding:16px;margin:20px 0;">
          <p style="margin:0 0 8px;font-size:13px;"><strong>Solicitação:</strong> {sol.numero}</p>
          <p style="margin:0 0 8px;font-size:13px;"><strong>Período:</strong> {sol.data_inicio.strftime('%d/%m/%Y')} a {sol.data_fim.strftime('%d/%m/%Y')}</p>
          <p style="margin:0 0 8px;font-size:13px;"><strong>Destino:</strong> {sol.estado}{' — ' + sol.local_inicio if sol.local_inicio else ''}</p>
          <p style="margin:0 0 8px;font-size:13px;"><strong>Veículo:</strong> {sol.categoria_veiculo or '-'} ({sol.tipo_diaria or '-'})</p>
          {motorista_info}
        </div>
        <p style="font-size:13px;"><strong>Observações importantes:</strong></p>
        <ul style="font-size:13px;line-height:1.8;">
          <li>O serviço baseia-se em diária de {sol.tipo_diaria or '10h'}, respeitando os horários previstos.</li>
          <li>É vedado o uso de veículo oficial para transporte individual residência/trabalho.</li>
          <li>Ao final do serviço, assinar a requisição de transporte.</li>
          <li>Cancelamentos devem ser comunicados com antecedência mínima de 3 horas.</li>
        </ul>
        <p>Atenciosamente,<br><strong>DITRAN/MDS</strong></p>
      </div>
      <div style="background:#f8fafc;padding:12px 30px;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 8px 8px;">
        <p style="margin:0;font-size:11px;color:#94a3b8;">Sistema de Controle de Diárias — MDS/DITRAN.</p>
      </div>
    </div>
    """


def email_alerta_saldo_html(saldo):
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:#dc2626;padding:20px 30px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;font-size:18px;">&#9888; Alerta de Saldo Baixo</h2>
        <p style="color:#fecaca;margin:4px 0 0;font-size:13px;">DITRAN / MDS — Sistema de Controle de Diárias</p>
      </div>
      <div style="background:#fff;padding:30px;border:1px solid #e2e8f0;border-top:none;">
        <h3 style="color:#dc2626;margin-top:0;">Saldo de Diárias Baixo</h3>
        <p>O saldo de diárias está abaixo do limite recomendado.</p>
        <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px;margin:20px 0;">
          <p style="margin:0 0 8px;font-size:14px;"><strong>Saldo:</strong> {saldo.descricao or 'Saldo Ativo'}</p>
          <p style="margin:0 0 8px;font-size:14px;"><strong>Total:</strong> {saldo.saldo_total} diárias</p>
          <p style="margin:0 0 8px;font-size:14px;"><strong>Usado:</strong> {saldo.saldo_usado} diárias</p>
          <p style="margin:0 0 8px;font-size:14px;"><strong>Comprometido:</strong> {saldo.saldo_comprometido} diárias</p>
          <p style="margin:0;font-size:16px;font-weight:bold;color:#dc2626;"><strong>Disponível: {saldo.saldo_livre} diárias</strong></p>
        </div>
        <p>Acesse o sistema para verificar e tomar as providências necessárias.</p>
        <p>Atenciosamente,<br><strong>Sistema DITRAN/MDS</strong></p>
      </div>
    </div>
    """
