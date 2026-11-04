# Fortune Texugo — Risca Faca

Entretenimento promocional gratuito: HTML/CSS/JavaScript, FastAPI, PostgreSQL e Railway. Não existem depósitos, apostas com dinheiro, saques ou compra de giros. O visual da máquina e os símbolos existentes foram preservados.

**Estado local atual (04/11/2026):** premiação ativada por solicitação expressa do responsável nesta conversa. Novas vitórias consomem estoque. Instalações novas continuam em demonstração por padrão. Estoque, resultados, códigos e retiradas anteriores foram preservados. A ativação exige campanha regularizada, configuração explícita de `PRIZES_ENABLED=true`, referência real em `AUTHORIZATION_REFERENCE` e chave administrativa forte. Não houve deploy no Railway.

## Contas e participação

- Cadastro: nome completo, CPF, Instagram, senha com oito caracteres ou mais, confirmação de senha, declaração de 18 anos e aceite dos Termos de Uso e ciência do Aviso de Privacidade.
- CPF com dígitos verificadores válidos e Instagram normalizado são únicos no PostgreSQL. CPF e Instagram informados **não comprovam identidade ou titularidade**. Por decisão do responsável, não há revisão prévia de identidade, Turnstile ou exigência de SMS para novas contas. Rate limiting e revisão administrativa posterior continuam disponíveis; cadastros com dados válidos de pessoas diferentes não garantem pessoas distintas acessando o jogo.
- O CPF é cifrado com Fernet e identificado para duplicidade por HMAC-SHA256 com chave distinta. Listagens mostram apenas os dois últimos dígitos. Senhas usam exclusivamente Argon2id.
- Login por CPF e senha; também por Instagram e senha para permitir continuidade após eliminação do CPF. Sessão aleatória de sete dias, com digest no banco e cookie HttpOnly, SameSite=Lax e Secure em produção. O perfil do participante mostra somente nome, Instagram e saldo; o histórico detalhado fica no painel administrativo. Nenhuma credencial de conta vai para localStorage. Logout revoga a sessão; suspensão revoga todas as sessões da conta.
- Cada cadastro válido recebe três giros. O contador mostra **GIROS: X**, somente com o saldo disponível, sem denominador. Conta autenticada, ativa e saldo positivo são obrigatórios para girar. Sem sessão, GIRAR abre login; sem saldo, abre RESGATAR GIROS.
- Indicação usa o próprio **@ do Instagram**, sem códigos aleatórios. O indicador deve existir e estar ativo; o vínculo com seu ID é registrado exclusivamente no cadastro. Um cadastro válido credita automaticamente um giro ao indicador, uma única vez, **sem limite de convites ou bônus**. Visitas ao link não geram crédito. Não há autoindicação, troca posterior de indicador ou dupla concessão concorrente. Quem já ganhou não recebe novos giros.
- MINHAS INDICAÇÕES mostra @, total de pessoas indicadas e giros recebidos, sem contador de limite. Use COPIAR @ para enviar seu identificador ou COPIAR LINK DE INDICAÇÃO para copiar o convite com `?ref=@usuario`. O link usa o domínio atual e preenche o Instagram do indicador no cadastro; outros parâmetros e fragmentos da página não são compartilhados. O saldo atualiza ao recuperar foco, a cada 30 segundos em página visível e pelo botão de atualização.
- Códigos promocionais concedem giros a contas ativas sem prêmio anterior, dentro de validade, disponibilidade e limite global. Um resgate por conta, obrigatório em todos os códigos. Repetir a mesma operação após falha de rede recupera o resultado sem conceder novamente.

O aviso acima da máquina informa que, para concorrer aos prêmios, é necessário seguir **@risca.faca**. É somente um aviso: não consulta seguidores nem bloqueia automaticamente a conta.

## Máquina e histórico de saldo

O mecanismo de resultado existente foi mantido. A chance base inicial é 2% por giro elegível, editável no painel; cada prêmio tem multiplicador inteiro, limitado a 100% efetivos. Os valores atuais do banco não são sobrescritos na migração. Em demonstração, nenhum giro concede prêmio, mesmo com chance configurada em 100%.

O administrador define a sequência dos prêmios: o primeiro item ativo com estoque, ordenado por prioridade e ID. Não há seleção aleatória entre tipos. Copos podem vir antes das dez pulseiras com multiplicador 2, conforme configuração existente. Reiniciar não repõe estoque nem créditos.

O servidor determina a vitória e representa o resultado na linha central, destacada por uma faixa translúcida, contorno dourado e setas laterais fixas. WILD é o coringa e usa somente `assets/simbolos/wild.svg`; a frase decorativa foi retirada. Outras linhas não premiam. Ao ganhar, o participante recebe popup com código copiável e a instrução **tire um print desta tela e mande no direct do @risca.faca**. Para novas vitórias de contas com CPF ainda disponível, o código usa o nome completo normalizado (letras minúsculas, sem espaços ou acentos) + os três últimos dígitos do CPF, por exemplo `joaosilva123`. O CPF é decifrado somente para gerar o código na transação da vitória. Códigos já emitidos são preservados. Se houver coincidência de nome e final de CPF, acrescenta-se `id` e o identificador da conta para evitar códigos ambíguos. Após a eliminação programada do CPF, usa-se o identificador opaco FT já atribuído, sem recuperar dados eliminados. O código de retirada contém esse fragmento e permanece no histórico do prêmio para sua retirada; informe o Instagram da conta para combinar retirada. Códigos legados com nome + telefone continuam válidos para retirada administrativa. Ao acabar o saldo sem prêmio, permanece o popup de convite da Calourada.

Um giro debita exatamente uma unidade. Player, resultado, prêmio, estoque e histórico são confirmados na mesma transação. Se houver vitória, o saldo restante é encerrado por uma movimentação adicional auditável, preservando a regra de fim imediato da participação. Requisições repetidas usam o mesmo `request_id` UUID e retornam o resultado original. Requisições concorrentes não tornam o saldo negativo. Novas contas usam saldo finito mesmo se a opção antiga de demonstração ilimitada estiver configurada.

`spin_ledger` registra CADASTRO, INDICACAO, CODIGO_PROMOCIONAL, GIRO_REALIZADO e AJUSTE_ADMINISTRATIVO, com quantidade assinada, saldo, origem, operação única e horário. Saldos legados ganham um registro inicial de importação, sem reconstituir ou inventar débitos anteriores; os giros antigos continuam em `spins`. Reaplicar migrações não duplica o saldo importado.

## Painel administrativo

Abra `/admin.html`, localmente em <http://localhost:8080/admin.html>. Acesse com `ADMIN_API_KEY`, disponível apenas no ambiente do servidor. O painel mantém a chave somente em memória e limpa dados exibidos ao sair.

- **Porcentagem de ganho:** controle destacado no início do painel, editável de 0 a 100%, com prévia da chance efetiva por prêmio e confirmação ao salvar. O aviso identifica quando a campanha está em demonstração, sem prêmios reais. Catálogo, sequência, multiplicadores, quantidades, pausa de prêmios e retirada única continuam disponíveis.
- **Códigos promocionais:** código personalizado ou aleatório seguro, giros, limite global, ativo/inativo e descrição. Na criação, não há campos de datas: cupons ativos ficam disponíveis imediatamente e não expiram. Na edição, é possível definir validade opcional; cupons antigos preservam suas datas. Exibe resgates e quantidade restante. Edite sem alterar resgates anteriores; não há renomeação de códigos e o limite não pode ficar abaixo do total já resgatado. Versões impedem edições administrativas sobre dados desatualizados.
- Indicadores: códigos totais, ativos, expirados, resgates e giros distribuídos. Consulta de resgates e exportação CSV protegida pela chave, com neutralização de fórmulas de planilha.
- **Usuários:** busca por nome ou Instagram, CPF mascarado, cadastro, status, saldo, giros realizados e bônus por origem. Selecione uma conta para histórico de saldo, giros e resgates. Ajustes positivos/negativos exigem justificativa e ID de operação; não é possível saldo negativo nem novos créditos para vencedores.
- Suspensão/reativação exige justificativa. Indicações, sinais de limites excedidos, cadastros em sequência e auditoria ficam em seções próprias; sinais não são prova automática de fraude.
- Retenção: execução manual da rotina, relatório de eliminações e registro de evidências de conferência de backups externos. Conservação excepcional de CPF pode ser documentada pela API com base legal e prazo.

**Migração de participantes antigos:** cadastro por telefone e bearer tokens ficam desativados por padrão. Os dados antigos não são apagados nem transformados automaticamente em contas com CPF e senha desconhecidos. Prêmios antigos continuam consultáveis e resgatáveis no painel. Novas contas devem ser criadas pelo novo formulário. Vincular uma conta a um participante legado exige conferência e migração planejada pelo responsável, sem supor titularidade pelo telefone. `LEGACY_ACCOUNTS_ENABLED=true` existe somente para compatibilidade e testes isolados; não o habilite em implantação pública. O fluxo antigo de SMS permanece isolado para compatibilidade, sem ser chamado por novas contas.

## Arquivos e personalização

| Arquivo | Responsabilidade |
|---|---|
| `index.html`, `assets/theme.css` | Layout e tema; ainda há estilos legados no HTML |
| `assets/game.js` | Máquina, animações, resultados e retomada de giro |
| `assets/accounts.js` | Cadastro/login, perfil, indicações e resgate |
| `assets/content.js` | Textos existentes, marca, caminhos das imagens, contato e ingresso |
| `assets/simbolos/`, `assets/art/` | Símbolos e arte da máquina; editáveis separadamente |
| `api/main.py` | Aplicação, estoque, giros e administração original |
| `api/accounts.py`, `api/security.py` | Contas, cookies, CPF, saldo, indicações e promoções |
| `api/participation.py` | Limites persistentes; compatibilidade com telefone |
| `api/retention.py`, `scripts/manage_data.py` | Eliminação e backups gerenciados cifrados |
| `api/sql/schema.sql`, `api/sql/accounts.sql` | Migrações aditivas aplicadas na inicialização |
| `legal/*.html`, `api/legal.py` | Minutas editáveis de termos e privacidade |
| `assets/admin*.js`, `assets/admin.css`, `admin.html` | Painel Python servido pela mesma aplicação |
| `tests/`, `scripts/check_accounts_browser.py` | Testes de API, banco e navegador |
| `supabase/` | Legado: não implantar |

O título da máquina é FORTUNE TEXUGO; a marca do cabeçalho continua `risca` dourado e `bet` vermelho. Não altere os IDs dos símbolos sem adaptar a API. As novas telas usam a mesma paleta e arquivos CSS existentes. A máquina concentra a ornamentação e o amarelo da marca; painéis laterais usam carvão, vermelho discreto e detalhes dourados suaves. A conta aparece em uma barra compacta acima do jogo e as regras ficam em uma seção expansível. Janelas e destaques usam os amarelos, vermelhos, preto e branco da referência Risca Faca. A paleta fica em `assets/brand.css`; títulos e botões usam ChunkFive, hospedada localmente em `assets/fonts/ChunkFive-Regular.ttf`, com licença preservada em `assets/fonts/OFL-ChunkFive.md` ([fonte oficial](https://github.com/theleagueof/chunk)). Textos longos e campos usam fonte sem serifa para leitura. Imagens e fontes continuam separadas; os textos das telas de conta estão em `assets/accounts.js` e na estrutura `index.html`, e os documentos jurídicos em `legal/`, sem alterar o backend para editar a redação.

## Ambiente local e Docker

Python 3.12 é a versão da imagem. PostgreSQL 16 é usado nos testes.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn api.main:app --reload --env-file .env
```

Configure as variáveis antes de iniciar; não publique arquivos de ambiente. Para Docker, use `.env.docker` ignorado pelo Git, com os segredos e `POSTGRES_PASSWORD`:

```sh
docker compose --env-file .env.docker up --build -d --wait
```

Jogo: <http://localhost:8080/>. Painel: <http://localhost:8080/admin.html>. PostgreSQL não tem porta pública. Assets são montados somente para leitura e atualizam ao recarregar; alterações em HTML/API exigem rebuild. O volume persiste ao reiniciar. `docker compose --env-file .env.docker down` para sem apagar os dados. Não use remoção de volume para testar.

Na entrega local, as chaves CPF foram geradas no arquivo ignorado, cookies sem Secure somente para HTTP local e premiação inicialmente desativada, depois ativada localmente por solicitação do responsável em 04/11/2026. Não houve envio de SMS nem conexão a Turnstile. Uma prévia estática serve apenas para visualizar a máquina: o fluxo de contas requer a API na mesma origem.

## Variáveis e Railway

Para a publicação guiada, siga [RAILWAY_DEPLOY.md](RAILWAY_DEPLOY.md). O arquivo privado `.env.railway` é preparado localmente para copiar no RAW Editor; não é publicado no repositório.

| Variável | Configuração |
|---|---|
| `DATABASE_URL` | URL privada do PostgreSQL, por exemplo `${{Postgres.DATABASE_URL}}` |
| `PHONE_PEPPER` | Segredo distinto, pelo menos 32 caracteres, também usado para limites; preserve bancos legados |
| `ADMIN_API_KEY` | Segredo administrativo forte, mínimo recomendado 32 caracteres |
| `CPF_HMAC_KEY` | Segredo distinto de pelo menos 32 caracteres; gera o índice de duplicidade |
| `CPF_ENCRYPTION_KEY` | Chave Fernet gerada com a biblioteca cryptography |
| `COOKIE_SECURE` | `true` em Railway/HTTPS; `false` exclusivamente no HTTP local |
| `PUBLIC_ORIGIN` | Origem exata, por exemplo `https://seu-dominio.up.railway.app`, sem barra final |
| `RATE_LIMIT_ENABLED` | `true`; desabilitar apenas em testes isolados |
| `LEGACY_ACCOUNTS_ENABLED` | `false` |
| `PRIZES_ENABLED` | `false` até regularização e autorização aplicáveis |
| `AUTHORIZATION_REFERENCE` | Referência real do regulamento/autorização, exigida ao ativar prêmios |
| `DEMO_UNLIMITED_SPINS` | `false`; o legado não altera saldo de novas contas |
| `TERMS_VERSION`, `PRIVACY_VERSION` | `2026-11-04` inicialmente; atualizar após mudar os documentos |
| `DATA_CONTROLLER`, `PRIVACY_CONTACT`, `PRIVACY_LEGAL_BASIS` | Dados reais do responsável, canal e base legal definidos na revisão jurídica |
| `MANAGED_BACKUP_DIRECTORY` | Opcional: diretório privado persistente, fora de `assets/` |
| `BACKUP_ENCRYPTION_KEY` | Opcional: outra chave Fernet para backups gerenciados |

Gere cada segredo textual separadamente com `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Gere cada chave Fernet separadamente com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Não troque a chave HMAC sem migrar os índices de CPF; não troque a chave de cifra sem recifrar os dados. Guarde segredos fora do GitHub, frontend, logs e capturas compartilhadas.

No Railway, crie serviços PostgreSQL e API a partir do Dockerfile, configure as variáveis no serviço da API e um domínio HTTPS. `/health` verifica o banco. O servidor aplica as migrações antes de aceitar conexões, sem repor dados. Configure o encaminhamento de endereços somente por proxies confiáveis; a aplicação usa `request.client.host`, sem confiar diretamente em `X-Forwarded-For`. Teste a limitação por IP no domínio final, pois um proxy mal configurado pode agrupar todos os visitantes no mesmo limite.

Valide em banco separado antes de publicar: cadastro, login, recarga, resgate, estoque e painel. Configure o inventário/retensão dos backups do provedor e uma execução periódica independente de `python scripts/manage_data.py cleanup` se o serviço puder ficar desligado; a API também executa a rotina na inicialização e a cada hora enquanto está ativa. Nenhum deploy público foi executado por esta entrega.

## Segurança e limites

Cookies exigem CSRF por `X-CSRF-Token` para operações autenticadas, fornecido por `/api/account/me` e mantido apenas em memória. Login/cadastro aceitam JSON; requisições de navegador com origem externa são rejeitadas, sem CORS permissivo. Consultas são parametrizadas. Validações não devolvem CPF ou senha no erro. Respostas API são `no-store`, com proteção contra interpretação de conteúdo e enquadramento.

Limites PostgreSQL persistentes: cadastro 20/IP/hora e 5/CPF/hora; login 30/IP/15 minutos e 8/identificador/15 minutos; giros 300/IP/minuto; resgates 60/IP e 20/conta/15 minutos. Tentativas rejeitadas contam e retornam 429. Os identificadores dos limites são derivados com segredo. Na ausência de CAPTCHA ou prova de identidade, esses limites reduzem abuso, mas não impedem múltiplos cadastros com CPFs distintos válidos. Não configure APM/proxy para capturar corpos de cadastro ou login.

## Termos, privacidade e eliminação do CPF

`/termos` e `/privacidade` são **minutas**, com versão e dados do responsável configuráveis. O aceite e declaração de maioridade registram horário do PostgreSQL e versões. Os documentos precisam de revisão jurídica e preenchimento de responsável, canal, base legal, operadores, transferências e retenção das demais informações antes da publicação. O sistema não inventa esses dados.

A eliminação é programada para **05/12/2026, 00h de São Paulo (03h UTC)**. Remove cifra, HMAC e fragmento de CPF; a auditoria guarda contagem e horário, sem cópias do documento. Login posterior usa Instagram e senha. Novos cadastros com CPF são encerrados no prazo, pois manter uma regra de CPF único sem conservar um identificador não seria possível. Uma nova campanha exige uma política própria.

Conservação excepcional: `PUT /api/admin/users/{id}/cpf-hold` exige `reason`, `legal_basis` e `until_at` futuro com fuso, protegidos pela chave administrativa. A rotina preserva somente até o prazo documentado e elimina depois. Isso não constitui validação jurídica da justificativa. Orientação de referência: [LGPD, artigos 15 e 16](https://www2.camara.leg.br/legin/fed/lei/2018/lei-13709-14-agosto-2018-787077-normaatualizada-pl.html).

Execução e relatório:

```sh
python scripts/manage_data.py cleanup --env-file .env
python scripts/manage_data.py backup --env-file .env
```

O segundo comando exige `pg_dump` compatível, diretório e chave de backup, cifra o arquivo completo sem escrever dump em texto puro e cria manifesto com expiração. A rotina elimina os arquivos gerenciados no prazo e registra o resultado. Para execução por API, use `/api/admin/retention/run` com a chave, consulte `/api/admin/retention` e registre evidências em `/api/admin/retention/backup-review`.

**Limite operacional:** a rotina não tem acesso a snapshots do Railway, cópias manuais, logs ou exportações de terceiros. O relatório os marca como pendentes de conferência; o responsável deve inventariar, excluir ou documentar conservação legítima e registrar evidências. Não há promessa de eliminação absoluta dessas cópias. Qualquer restauração deve executar a rotina antes de liberar acesso ao serviço.

## Rotas principais

| Método e caminho | Uso |
|---|---|
| `GET /api/config`, `GET /health` | Configuração pública e saúde |
| `POST /api/account/register` | Cadastro, aceite e sessão por cookie |
| `POST /api/account/login`, `POST /api/account/logout` | Acesso e revogação |
| `GET /api/account/me`, `GET /api/account/history` | Perfil, saldo, CSRF, indicações e histórico |
| `POST /api/spin` | `{request_id: UUID}`; cookie e CSRF obrigatórios |
| `POST /api/account/redeem` | `{code, operation_id: UUID}`; cookie e CSRF |
| `GET/POST /api/admin/codes` | Lista/indicadores e criação de código |
| `PUT /api/admin/codes/{id}` | Edição com versão |
| `GET /api/admin/codes/{id}/redemptions` | Participantes que resgataram |
| `GET /api/admin/code-redemptions.csv` | Exportação protegida |
| `GET /api/admin/users?q=` | Busca e saldos |
| `GET /api/admin/users/{id}/history` | Movimentações, giros e resgates |
| `POST /api/admin/users/{id}/balance` | `{amount, reason, operation_id}` |
| `PUT /api/admin/users/{id}/status` | `{status: active/suspended, reason}` |
| `GET /api/admin/referrals`, `/api/admin/suspicious`, `/api/admin/audit` | Indicações, sinais e auditoria |
| `GET /api/admin/stats`, `/api/admin/prizes`, `/api/admin/settings` | Administração já existente |
| `PUT /api/admin/settings`, `POST /api/admin/prize-types`, `PUT /api/admin/prize-types/{id}` | Catálogo e chance |
| `POST /api/admin/redeem` | Retirada única de prêmio |
| `GET /docs` | Contratos e campos completos |

## Testes

```sh
node --check assets/game.js
node --check assets/accounts.js
node --check assets/admin.js
node --check assets/admin-accounts.js
node --test tests/game.test.cjs
PG_BINDIR=/opt/homebrew/opt/postgresql@16/bin .venv/bin/python scripts/run_postgres_tests.py
PG_BINDIR=/opt/homebrew/opt/postgresql@16/bin .venv/bin/python scripts/check_accounts_browser.py
```

O primeiro script Python cria e remove um cluster PostgreSQL privado. Alternativamente, use `FORTUNE_TEST_DATABASE_URL` apontando para banco exclusivo de testes. Cada teste usa um schema descartável; sem essa configuração, os testes de banco são pulados. O teste de navegador requer `pip install playwright` e Chrome instalado; usa outro cluster e API temporários, sem alterar o banco da campanha nem conceder prêmios reais.

Validação da implementação: **124 testes Python e 19 JavaScript passaram**, cobrindo validações, autenticação, CSRF, concorrência, indicações, limites de resgates, ajustes, migrações reaplicadas e eliminação de CPF. Teste real em Chrome passou para cadastro, sessão após recarga, indicação, resgate, giro, perfil, login/logout, painel e documentos, nas larguras 320, 390 e 1440. Isso não constitui teste de capacidade do Railway ou validação jurídica.
