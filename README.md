# 🎰 Fortune Texugo — Risca Faca

> **Status:** V4.1 em desenvolvimento. Interface demonstrativa disponível; premiação real **desativada** por padrão. Não lançar a promoção antes de autorização, regulamento aprovado e testes.

## 1. Visão do produto
Experiência promocional gratuita para a Calourada de Engenharia UFES, 05/12/2026, 21h, Casa Brava. Identidade do Risca Faca, estética de cassino Las Vegas vintage: preto, vinho/vermelho e dourado. Mascote Riquelme (texugo) e símbolos exclusivos. A experiência deve ser leve, divertida e funcionar muito bem no celular. **Não há apostas, depósitos ou compra de giros.**

### Regras pretendidas (sujeitas à autorização)
- Nome + WhatsApp com DDD; um cadastro por número.
- 3 giros gratuitos por participante.
- Probabilidade configurada em 2% **por giro**, com no máximo 5 copos distribuídos no total.
- Prêmio físico: copo Risca Faca; código único de retirada.
- Ao esgotar o estoque, nenhum novo prêmio é concedido.
- Regulamento e comunicação precisam explicar que a chance de ganhar não equivale a garantia de premiação.
- A grade de símbolos é visual: a decisão de premiação é calculada no servidor. **Antes do lançamento, alinhar a representação visual dos símbolos ao mecanismo e ao regulamento aprovado, para não induzir o participante a erro.**
- **Nunca habilitar premiação real sem autorização e revisão jurídica.**

## 2. Arquivos
| Arquivo | Função |
|---|---|
| `index.html` | Landing page e caça-níquel responsivo |
| `admin.html` | Login de administrador, estatísticas e retirada |
| `supabase/schema.sql` | Tabelas, RLS, função transacional de giro |
| `supabase/functions/register/index.ts` | Cadastro no servidor |
| `supabase/functions/spin/index.ts` | Sorteio e consumo de giro no servidor |
| `supabase/functions/admin/index.ts` | Ações autenticadas de administração |
| `.gitignore` | Exclusão de arquivos de ambiente |

## 3. Já implementado
- [x] Layout responsivo 3×3 com máquina vermelha/dourada
- [x] Cadastro nome + WhatsApp na interface
- [x] Modo demonstração local sem backend e sem prêmios
- [x] Três giros por cadastro na lógica do backend
- [x] Probabilidade de 2% no backend (configurável no banco)
- [x] Estoque global de cinco copos em transação SQL
- [x] Código de retirada único e resgate administrativo
- [x] Supabase RLS e bloqueio de acesso direto às tabelas
- [x] Autenticação do administrador via Supabase Auth
- [x] Rolos animados com parada sequencial, iluminação e reflexos
- [x] Efeito de vitória com confetes e destaque da máquina
- [x] Respeito a `prefers-reduced-motion`
- [x] Premiação real bloqueada por padrão
- [ ] Integração real com um projeto Supabase
- [ ] Publicação e validação no GitHub Pages

## 4. Direção de arte e experiência — backlog prioritário
- [ ] **Mascote:** usar arte original do Riquelme, bem integrada ao topo da máquina; sem aparência genérica de IA.
- [ ] **Símbolos:** substituir emojis por SVG/PNG próprios (bananinha, flor-de-lis, texugo, fichas, copo, carta). Otimizar peso e contraste.
- [ ] **Máquina:** aprimorar moldura em SVG/CSS, placas, lâmpadas, profundidade e brilho, sem poluir o layout.
- [ ] **Rolos:** animação com faixas contínuas, aceleração e desaceleração física, em vez de troca aleatória de símbolos.
- [ ] **Feedback:** estados claros de cadastro, girando, erro, sem prêmio, vitória e fim de giros.
- [ ] **Som opcional:** efeitos sonoros originais, desativados inicialmente, com botão de silenciar.
- [ ] **Acessibilidade:** foco de teclado, contraste, leitura por tela, estados ARIA, redução de movimento.
- [ ] **Mobile:** testar 320px–430px, teclado aberto, orientação e celulares de desempenho baixo.
- [ ] **Identidade:** usar tipografia consistente com os posts do Risca Faca e referências vintage Vegas.
- [ ] **Conversão:** link real de ingressos, CTA claro e seção de informações da Calourada.
- [ ] **Compartilhamento:** metatags Open Graph, favicon, preview social, QR code e analytics com consentimento.

## 5. Backend e antifraude — obrigatório antes de produção
- [ ] **Verificação de posse do WhatsApp:** OTP via SMS ou WhatsApp; nome + número sozinho não impede números falsos ou de terceiros.
- [ ] **Rate limiting** por IP, número e sessão nas funções de cadastro e giro.
- [ ] **CAPTCHA/Turnstile** no cadastro, validado no servidor.
- [ ] **Persistência de sessão** segura para sobreviver a recargas sem permitir reutilização indevida.
- [ ] **Auditoria de giros e retiradas** com registros de tempo, versão do regulamento e ID da campanha.
- [ ] **Idempotência do giro** para não consumir dois giros em tentativas repetidas após falhas de rede.
- [ ] **Segurança do sorteio:** testes estatísticos, aleatoriedade no servidor e registro verificável do resultado.
- [ ] **Concorrência:** testes de centenas de giros simultâneos para garantir estoque <= 5.
- [ ] **Admin:** listar vencedores, status, busca por código, exportação controlada e confirmação de retirada com dupla checagem.
- [ ] **Privacidade/LGPD:** aviso de finalidade, retenção, exclusão, política de privacidade e consentimentos adequados.
- [ ] **Restringir CORS** ao domínio de produção e configurar logs sem expor telefone, token ou códigos.
- [ ] **Revisão de permissões:** manter service role e `PHONE_PEPPER` apenas no servidor.
- [ ] **Revisão do SQL:** garantir que a função `fortune_do_spin` seja executável apenas pelo papel de serviço e não exposta publicamente.
- [ ] **Conferência presencial:** validar vencedor e impedir retirada duplicada.

## 6. Configuração Supabase (desenvolvimento)
1. Criar projeto em [Supabase](https://supabase.com/).
2. Executar `supabase/schema.sql` no SQL Editor.
3. Configurar segredo `PHONE_PEPPER` longo e aleatório nas Edge Functions; não colocar no repositório.
4. Fazer deploy das funções `register`, `spin` e `admin` e configurar corretamente autenticação e CORS.
5. Inserir `SUPABASE_URL` e `SUPABASE_ANON_KEY` (chave **pública**) em `index.html` e `admin.html`. **Jamais** inserir a service role no frontend.
6. Criar usuário em Supabase Auth e inserir seu UUID em `fortune_admins`.
7. Testar cadastro, giro, fim de créditos, bloqueio de prêmio, painel e retirada.
8. Manter `fortune_config.authorized = false` durante desenvolvimento.

**Atenção:** a flag `authorized` é apenas uma trava técnica. Ela não substitui autorização oficial, e não deve ser alterada sem comprovação e revisão do regulamento.

## 7. Publicação da prévia
No GitHub: **Settings → Pages → Deploy from a branch → main → /(root)**.
Endereço esperado depois do deploy: `https://olivste.github.io/fortune-texugo/`.
GitHub Pages hospeda apenas o frontend estático; as Edge Functions ficam no Supabase.

Sem URL e chave Supabase configuradas, o `index.html` funciona como **prévia local**. O painel administrativo requer backend.

## 8. Plano de entregas
**Fase A — visual:** mascote e ícones originais, animação de rolos contínua, melhorias de responsividade, polimento do cassino.

**Fase B — infraestrutura:** projeto Supabase, migrations, autenticação, sessões, auditoria, testes automatizados.

**Fase C — antifraude:** OTP, CAPTCHA, limites de requisições, observabilidade e validação de retirada.

**Fase D — lançamento:** autorização, regulamento, privacidade, teste de carga, link de ingressos, revisão de segurança e publicação.

## 9. Critérios de aceite
- Nenhum prêmio real é entregue no modo demonstração.
- Três giros por participante verificado, sem possibilidade de reiniciar com refresh.
- Estoque nunca negativo, nem superior a cinco copos distribuídos.
- Cada código de retirada é único e resgatável uma única vez.
- O frontend não escolhe vencedor nem manipula estoque.
- Experiência acessível e fluida em celular.
- Interface informa claramente quando é demonstração e quando a campanha está autorizada.
- A mecânica, probabilidades e peças publicitárias correspondem ao regulamento autorizado.

---
**Responsável:** Risca Faca. Projeto em desenvolvimento; não utilizar como sistema promocional de produção sem as etapas pendentes.


## 10. Personalização de imagens e textos (V5)

A referência visual é o feed do Risca Faca: **cassino ilustrado, cartaz vintage, cortinas vermelhas, fundo preto, dourado envelhecido e marquise Vegas**. Não usar emojis como arte final.

**Tudo separado por arquivo:**

| Caminho | O que trocar |
|---|---|
| `assets/content.js` | **Todos os nomes, títulos, slogans, data/local e caminhos das imagens** |
| `assets/theme.css` | Cores, molduras, tipografia e efeitos visuais |
| `assets/mascote.svg` | Ilustração provisória do Riquelme no medalhão |
| `assets/cassino.svg` | Fundo ilustrado do cassino |
| `assets/simbolos/bananinha.svg` | Símbolo da bananinha |
| `assets/simbolos/flor-de-lis.svg` | Símbolo flor-de-lis |
| `assets/simbolos/texugo.svg` | Símbolo do texugo |
| `assets/simbolos/copo.svg` | Símbolo do copo |
| `assets/simbolos/carta.svg` | Símbolo da carta |
| `assets/simbolos/ficha.svg` | Símbolo da ficha |

**Como trocar:** envie a nova imagem para a pasta `assets/` (PNG, WebP ou SVG) e atualize o caminho correspondente em `assets/content.js`. As ilustrações SVG atuais são **placeholders editáveis**, não reproduções fiéis da arte enviada.

**Próximos ajustes visuais:** usar o Riquelme oficial da arte, criar símbolos na mesma linguagem do post, transformar o fundo em um cassino ilustrado em camadas e refinar o movimento dos rolos.

**Atenção técnica:** os símbolos são apresentados no cliente. O resultado de premiação é determinado no servidor, sem dependência da combinação visual. Essa distinção deve estar explícita na experiência e no regulamento antes de qualquer lançamento.
