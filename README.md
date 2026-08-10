# HUB-J FLUX

Sistema de controle financeiro completo, multi-tenant (famílias/empresas
clientes), hospedado no Railway.

## Fase 1 (atual): Autenticação + estrutura multi-tenant

- Login via Google OAuth (Authlib)
- Duas camadas de autorização: identidade (Google) + lista de usuários
  permitidos (tabela `usuarios`), revalidada em toda requisição
- Hierarquia: Super Admin → Admin do Cliente → Usuário comum
- Tela de Gestão de Clientes (Super Admin): criar organização + primeiro admin

## Variáveis de ambiente necessárias

| Variável | Descrição |
|---|---|
| `DATABASE_URL` | String de conexão do Postgres |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Credenciais OAuth do Google Cloud Console |
| `SESSION_SECRET_KEY` | Chave aleatória para assinar o cookie de sessão |
| `SUPER_ADMIN_EMAIL` | E-mail que vira `super_admin` automaticamente no primeiro login |
| `APP_BASE_URL` | URL pública do app (usada para montar o redirect do OAuth) |

## Rodando localmente

```bash
pip install -r requirements.txt
export DATABASE_URL=...  # string de conexão pública do Postgres no Railway
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...
export SESSION_SECRET_KEY=...
export SUPER_ADMIN_EMAIL=...
python app.py
```

Acesse http://localhost:5000/login-page
