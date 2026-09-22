# Saldo de Diárias

Sistema web para controle de saldo de diárias de veículos alugados, com gestão de solicitações, motoristas e relatórios.

## Funcionalidades

- Dashboard com KPIs, gráfico de saldo e serviços por região
- Cadastro e acompanhamento de solicitações com workflow de 7 estágios
- Gestão de saldo com histórico de movimentações
- Cadastro de motoristas com histórico de viagens
- Importação de solicitações via planilha Excel (formato SCDP)
- Calendário mensal de serviços
- Relatórios com gráficos e relatório de conformidade
- Comentários e anexos nas solicitações
- Notificações por e-mail configuráveis
- Controle de acesso por perfil (admin, gestor, operador)
- Suporte mobile completo e instalável como PWA

## Tecnologias

- Python / Flask
- SQLAlchemy + SQLite
- Bootstrap 5
- Flask-Login / Flask-Mail
- Chart.js
- openpyxl

## Como rodar

```bash
# Execute o arquivo run.bat — ele cria o ambiente virtual,
# instala as dependências e inicia o servidor

run.bat
```

Acesse em: `http://localhost:5000`

Login padrão: matrícula `admin` / senha `admin123`
