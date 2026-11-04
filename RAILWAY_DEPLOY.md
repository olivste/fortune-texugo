# Publicar Fortune Texugo no Railway

Branch preparada: `deploy/railway-ready`. O ambiente local e seus prêmios não são alterados por este procedimento. O primeiro ambiente remoto começa em demonstração, em banco novo. Não copie o banco local de testes para a campanha sem uma decisão explícita.

## 1. Criar o projeto e o PostgreSQL

1. Entre em https://railway.com/dashboard com a conta GitHub `olivste`.
2. Crie um **New Project → Empty Project**.
3. No projeto, escolha **New / Create → Database → PostgreSQL**.
4. Mantenha o serviço com o nome **Postgres**. A referência de conexão no arquivo local usa esse nome.
5. Espere o banco iniciar. Não é necessário abrir uma porta pública para o banco.

## 2. Adicionar a aplicação

1. No mesmo projeto, escolha **New / Create → GitHub Repo**.
2. Selecione `olivste/fortune-texugo`. Se não aparecer, configure o acesso do Railway a esse repositório na integração GitHub.
3. Nas configurações de origem da aplicação, selecione a branch **deploy/railway-ready**.
4. Mantenha o diretório raiz do repositório. O Dockerfile já existe e define o comando de inicialização usando `PORT`.
5. Se uma implantação iniciar antes das variáveis, poderá falhar por falta de configuração. Configure as variáveis abaixo e implante novamente; não apague o banco.

## 3. Configurar as variáveis privadas

O arquivo **`.env.railway`**, gerado localmente e ignorado pelo Git, contém segredos próprios para este ambiente. Ele não é um arquivo para publicar nem enviar por chat.

1. Abra o serviço da aplicação → **Variables → RAW Editor**.
2. Copie o conteúdo de `.env.railway` para esse editor e salve.
3. Confirme a referência `DATABASE_URL=${{Postgres.DATABASE_URL}}`. Se o serviço do banco tiver outro nome, use **Add Reference** para selecionar seu `DATABASE_URL`.
4. A origem usa `PUBLIC_ORIGIN=https://${{RAILWAY_PUBLIC_DOMAIN}}`. A variável deve resultar no domínio HTTPS definitivo, sem barra final. Se necessário, substitua pelo endereço literal depois de gerar o domínio.
5. Mantenha `COOKIE_SECURE=true`, `RATE_LIMIT_ENABLED=true`, `LEGACY_ACCOUNTS_ENABLED=false`, `PRIZES_ENABLED=false` e `DEMO_UNLIMITED_SPINS=false` neste teste.
6. Revise e aplique as alterações em **Deploy**.

As chaves de CPF e autenticação precisam continuar as mesmas nos próximos deploys deste banco. Não regenere o arquivo para atualizar CSS ou imagens. Instalações que reutilizem dados existentes precisam usar as chaves correspondentes a esses dados.

O responsável e contato fornecidos pelo usuário já estão no arquivo local. A base legal permanece pendente de definição/revisão; a aplicação não a inventa.

## 4. Gerar o domínio e verificar

1. Serviço da aplicação → **Settings → Networking / Public Networking → Generate Domain**.
2. Utilize a porta do servidor definida pelo Railway (`PORT`); o Dockerfile já a respeita.
3. Confirme em Variables que `PUBLIC_ORIGIN` corresponde exatamente à origem HTTPS gerada. Aplique as alterações se editar esse valor.
4. Abra `https://SEU-DOMINIO/health`: deve mostrar `status: ok` e `mode: demo`.
5. Abra `/api/config`: deve retornar `accounts_enabled: true` e `demo: true`.
6. Abra `/`, `/termos`, `/privacidade` e `/admin.html`.

O healthcheck `/health` já está em `railway.json`. Ele confirma banco e servidor, mas não substitui os testes de participação.

## 5. Testar sem conceder prêmios

- Faça um cadastro com dados que possam ser utilizados legitimamente; confirme três giros iniciais.
- Saia e entre novamente; recarregue para verificar persistência da sessão.
- Faça os três giros em demonstração; o quarto não pode consumir saldo negativo.
- Entre no administrador usando a `ADMIN_API_KEY` do arquivo privado, sem compartilhar a chave.
- Crie um cupom de teste com poucos giros e resgates; resgate uma vez e confirme bloqueio da segunda tentativa.
- Teste uma indicação entre contas distintas; o indicador deve receber somente um giro por cadastro válido.
- Confira estoque, chance e multiplicadores. O banco novo não importa as configurações locais.
- Desative o cupom de teste e suspenda as contas de teste que não participarão da campanha. Não apague tabelas para limpar testes.

## 6. Antes de abrir a campanha

- Revise as minutas de termos e privacidade, a base legal, fornecedores e o regulamento aplicável. O responsável e o contato já foram informados; isso não encerra a revisão jurídica.
- Confirme a data de encerramento: a rotina elimina CPF e encerra novos cadastros com CPF em **05/12/2026 às 00h de São Paulo**. O login posterior continua por Instagram e senha.
- Configure backups do PostgreSQL no Railway e documente retenção/exclusão de snapshots, logs e exportações. A aplicação não tem acesso automático a cópias externas.
- Teste os limites de requisições no domínio e a configuração de proxies confiáveis.
- Configure o estoque real e as porcentagens aprovadas no painel. Confira o efeito dos multiplicadores; 99% com multiplicador 3 resulta em 100% efetivos.
- Antes da ativação, confira se há contas de teste e prêmios/cupom de teste ainda disponíveis.

## 7. Ativar prêmios após a conferência

Somente quando o responsável decidir ativar a campanha remota: defina `AUTHORIZATION_REFERENCE` com a referência real aplicável, altere `PRIZES_ENABLED=true` e aplique um novo deploy. Confirme `mode: live` em `/health`. Giros vencedores passarão a consumir o estoque do banco remoto. Não force vitórias nem estoque no banco da campanha para testar.

O painel ficará em **`https://SEU-DOMINIO/admin.html`**. Os segredos de produção não precisam ser iguais aos do Docker local.

Referências oficiais: [criação de projeto](https://docs.railway.com/quick-start), [variáveis e RAW Editor](https://docs.railway.com/variables), [PostgreSQL](https://docs.railway.com/databases/postgresql), [healthchecks](https://docs.railway.com/deployments/healthchecks).
