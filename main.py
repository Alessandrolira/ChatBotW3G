import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import openai  # type: ignore
import requests  # type: ignore
from flask import Flask, jsonify, request  # type: ignore
import re

load_dotenv()

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

VALIDATION_TOKEN = "2nDIUwqGLb779gcn9LzQMVSgACn"
MAX_TOKENS = 3500  # Limite de tokens para o histórico
MAX_RESPONSE_LENGTH = 1500  # Limite para o tamanho da resposta

# Variável para armazenar o histórico de conversas por usuário
historico_conversa = {}
mensagens_processadas = set()


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        # Validação do webhook
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode and token:
            if mode == 'subscribe' and token == VALIDATION_TOKEN:
                print("WebHook verificado com sucesso")
                return challenge, 200
            else:
                return "Token de verificação inválido", 403

    elif request.method == 'POST':
        # Tratamento de mensagens recebidas
        data = request.get_json()
        # print(f"dados recebidos: {data}")

        if ('entry' in data and
                'changes' in data['entry'][0] and
                'value' in data['entry'][0]['changes'][0] and
                'messages' in data['entry'][0]['changes'][0]['value']):

            mensagem = data['entry'][0]['changes'][0]['value']['messages'][0]['text']['body']
            sender = data['entry'][0]['changes'][0]['value']['messages'][0]['from']
            message_id = data['entry'][0]['changes'][0]['value']['messages'][0]['id']  # Pegando o ID da mensagem

            print(f"MENSAGEM ENVIADA ========= {mensagem}")

            # Verifique se essa mensagem já foi processada
            if message_id in mensagens_processadas:
                print(f"Mensagem com ID {message_id} já foi processada.")
                return "Mensagem já processada", 200

            # Adicione o ID da mensagem à lista de mensagens processadas
            mensagens_processadas.add(message_id)

            # Adiciona a mensagem ao histórico do usuário
            if sender not in historico_conversa:
                historico_conversa[sender] = []  # Inicializa o histórico do usuário

            historico_conversa[sender].append({'role': 'user', 'content': mensagem})

            # Envie uma mensagem de "aguarde"
            enviarMensagem(sender, "⏳ *Aguarde um momento...*\n_Estou processando sua solicitação..._")

            tema = categorizarPergunta(mensagem)

            if tema in ['beneficiario', 'beneficiarios', 'Beneficiário', 'Beneficiários']:
                consultaSQL = buscarBeneficiarios(mensagem)
                prompt_sistema = formatarDadosParaTexto(consultaSQL)
            elif tema == 'rede' or tema == 'Rede':
                consultaSQL = buscarRede(mensagem)
                prompt_sistema = formatarDadosParaTextoRede(consultaSQL)
            elif tema == 'plano':
                consultaSQL = buscarPlanos(mensagem)
                prompt_sistema = formatarDadosParaTextoPlano(consultaSQL)
            elif tema == 'BuscaRedeBeneficiário':
                try:
                    consultaSQL = buscarRedePorEspecialidade(mensagem)
                    print(consultaSQL)
                    prompt_sistema = formatarDadosParaTextoRede(consultaSQL)
                except:
                    prompt_sistema = """Para realizar essa busca é necessário que possuam três parametros:
                    1. nome do beneficiario
                    2. especialidade buscada
                    3. municipio

                    Atente-se para escrever o nome correto das informações
                    """
            else:
                prompt_sistema = "Desconhecido"

            resposta = gerarRespostaChatGPT(sender,
                                            f"Todo o conteudo externo deve ser ignorado e apenas considerado o seguinte texto: '{prompt_sistema}'")
            print(f"Esse é o PROMPT DE SISTEMA {prompt_sistema}")

            # Verifica o tamanho da resposta
            if len(resposta) > MAX_RESPONSE_LENGTH:
                enviarMensagem(sender, "A resposta é grande demais, poderia ser mais específico?")
            else:
                enviarMensagem(sender, resposta)

            return jsonify({'status': 'sucesso', 'mensage': 'Mensagem processada com sucesso'}), 200

    return "Error", 400


def enviarMensagem(to, message):
    url = 'https://graph.facebook.com/v20.0/477055852149378/messages'
    headers = {
        'Authorization': 'Bearer EAAO6yVjpe0sBOZCiIPJ59jAyYfgmBSB8nD3lm4hYtd6xZBaZCmg2gYO73fo8cYESFeP2l04yQfE9d6fSBLHmHNB0SZBfILDVNujE8ZA41KRo9vhrpO5xzZCltgDmHbeNnu1mSD0nhrSPzZB8qI70GVYQZA05NRgrJPgvQxZCH3J8Qybl2na4TbdbE5SSXVzt9w22i4oC4D3SKFGR0Pwt3TQmR36HvbULK',
        # Substitua pelo seu token de acesso
        'Content-Type': 'application/json'
    }
    payload = {
        'messaging_product': 'whatsapp',
        'to': to,
        'text': {'body': message}
    }

    response = requests.post(url, headers=headers, json=payload)
    print(f"Mensagem enviada: {response.text}")


def trim_historico(sender):
    total_tokens = sum(len(m['content'].split()) for m in historico_conversa[sender])
    while total_tokens > MAX_TOKENS:
        # Remove a primeira mensagem (mais antiga)
        historico_conversa[sender].pop(0)
        total_tokens = sum(len(m['content'].split()) for m in historico_conversa[sender])


def gerarRespostaChatGPT(sender, sistema_prompt=None):
    # Trime o histórico antes de gerar a resposta
    trim_historico(sender)

    # Pega o histórico de conversas do usuário
    contexto = historico_conversa[sender]

    if sistema_prompt:
        contexto.insert(0, {'role': 'system', 'content': sistema_prompt})

    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=contexto,  # Envia o histórico completo como contexto
            temperature=0
        )

        # Adiciona a resposta ao histórico
        resposta_texto = resposta.choices[0].message.content
        historico_conversa[sender].append({'role': 'assistant', 'content': resposta_texto})

        return resposta_texto

    except Error as e:
        print(e)
        return "Ocorreu um erro ao gerar a resposta."


def gerarRepostaChatGPTSemHistórico(contexto, pergunta):
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {'role': 'system', 'content': contexto},
                {'role': 'user', 'content': pergunta}
            ],
            temperature=0
        )

        return resposta.choices[0].message.content
    except Error as e:
        print(e)


def gerarRepostaChatGPT4SemHistórico(contexto, pergunta):
    try:
        resposta = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {'role': 'system', 'content': contexto},
                {'role': 'user', 'content': pergunta}
            ],
            temperature=0
        )

        return resposta.choices[0].message.content
    except Error as e:
        print(e)


def categorizarPergunta(pergunta):
    contexto = f"""
    Analise a seguinte pergunta: "{pergunta}". Categorize o tema da pergunta de acordo com as seguintes regras:

    1. Se a pergunta menciona o nome de uma pessoa, classifique como 'Beneficiário' (busque na tabela de movimentações). Qualquer pergunta sobre informações de um beneficiário se enquadra aqui.
    2. Se a pergunta fala sobre rede de atendimento, classifique como 'Rede' (busque na tabela de redeAmil).
    3. Se a pergunta se refere a planos ou valores de planos, classifique como 'Plano' (busque na tabela de planos).
    4. Se a pergunta busca informações sobre a rede credenciada de um beneficiário específico, classifique como 'BuscaRedeBeneficiário' (integre a busca de beneficiário e rede).

    Responda apenas com uma das seguintes palavras: beneficiarios, rede, plano, BuscaRedeBeneficiário. Lembre-se de que, ao perguntar sobre o status do plano, o foco é no beneficiário, mas se a pergunta busca encontrar um hospital para uma pessoa específica, será classificada como BuscaRedeBeneficiário.

    Forneça somente o tema em uma palavra.
    """

    tema = gerarRepostaChatGPT4SemHistórico(contexto, pergunta)
    print(f"O tema identificado foi o {tema}")
    return tema


def buscarBeneficiarios(mensagem):
    nome = None
    nomePlano = None

    contexto = f"""
        Dentro dessa mensagem: "{mensagem}" deve conter o nome de uma pessoa, identifique o nome da pessoa e me devolva apenas o nome dela.
    """

    nome = gerarRepostaChatGPTSemHistórico(contexto, mensagem)
    print(f"Esse é o nome: {nome}")

    if 'Não' in nome or 'não' in nome:
        contexto = f"""
            Dentro dessa mensagem: "{mensagem}" deve conter o nome de um plano, identifique o nome do plano e me devolva apenas o nome dele.
        """

        nomePlano = gerarRepostaChatGPTSemHistórico(contexto, mensagem)

    print(f"O nome identificado da pessoa é: {nome}")

    try:
        # Configurar conexão
        conexao = mysql.connector.connect(
            host="localhost",
            port=3306,
            user="root",
            password="",
            database="w3g_movimentacoes"
        )

        cursor = conexao.cursor()

        if nomePlano is None:
            # Criar consulta SQL
            consulta = """
            SELECT * FROM movimentacoes WHERE beneficiario LIKE %s
            """
            valor = f'%{nome}%'
            cursor.execute(consulta, (valor,))
            resultado = cursor.fetchall()
            return resultado
        else:
            consulta = """
            SELECT * FROM movimentacoes WHERE plano LIKE %s
            """
            valor = f'%{nomePlano}%'
            cursor.execute(consulta, (valor,))
            resultado = cursor.fetchall()
            return resultado

    except Error as e:
        print(f"Erro ao conectar ao MySQL: {e}")
        return []
    finally:
        if conexao.is_connected():
            cursor.close()
            conexao.close()


def buscarRede(mensagem):
    # Implementar lógica para buscar na tabela de rede
    contexto_especialidade = f"""
        Dentro dessa mensagem: "{mensagem}", identifique a especialidade buscada. Lembre-se de escrever apenas o nome da especialidade informada sem pontuação. Pode acontecer da especialidade não ser informada, caso isso aconteça informe "sem especialidade" maternidade ou maternidades é uma especialidade.
    """

    especialidade = gerarRepostaChatGPTSemHistórico(contexto_especialidade, mensagem)

    contexto_cidade = f"""
        Dentro dessa mensagem: "{mensagem}", identifique a cidade. Lembre-se de escrever apenas o nome da cidade informada sem pontuação e sem assento
    """
    cidade = gerarRepostaChatGPTSemHistórico(contexto_cidade, mensagem)

    contexto_nome_hospital = f"""
        Dentro dessa mensagem: "{mensagem}", identifique qual é o hospital buscado na pergunta sem nenhuma pontuação. Lembre-se de escrever apenas o nome do hospital informada sem pontuação e sem assento. Pode acontecer de não possuir nenhum hospital nesse caso escreva 'desculpe'
    """
    nome_hospital = gerarRepostaChatGPTSemHistórico(contexto_nome_hospital, mensagem)

    print(F"Nome do hospital --------------------- {nome_hospital}")
    print(F"Nome da especialidade --------------------- {especialidade}")
    print(F"Nome do municipio --------------------- {cidade}")

    try:
        conexao = mysql.connector.connect(
            host="localhost",
            port=3306,
            user="root",
            password="",
            database="w3g_movimentacoes"
        )

        cursor = conexao.cursor()

        if 'desculpe' in nome_hospital.lower():

            if "sem" in especialidade.lower():
                return "Informar a especialidade"

            consulta = """
            SELECT * FROM redeAmil WHERE elemento_de_divulgação LIKE %s AND municipio LIKE %s
            """
            cursor.execute(consulta, (f'%{especialidade}%', f'%{cidade}%'))

        else:

            consulta = """
            SELECT * FROM redeAmil WHERE nome_prestador LIKE %s
            """
            cursor.execute(consulta, (f'%{nome_hospital}%',))

            print(f"CURSOR ========== {cursor.fetchall()}")

            if cursor.fetchall() == []:
                return "Hospital não encontrado"

        resultados = cursor.fetchall()

        return resultados

    except Error as e:
        print("Erro ao conectar ao MySQL: ", e)
        return []
    finally:
        if conexao.is_connected():
            cursor.close()
            conexao.close()


def buscarPlanos(mensagem):
    contexto = f"""
    Dentro dessa mensagem: "{mensagem}", identifique o nome do plano e me devolva apenas o nome dele.
    """
    plano = gerarRepostaChatGPTSemHistórico(contexto, mensagem)

    try:
        conexao = mysql.connector.connect(
            host="localhost",
            port=3306,
            user="root",
            password="",
            database="w3g_movimentacoes"
        )

        cursor = conexao.cursor()

        consulta = """
        SELECT * FROM planosAmil WHERE nome_plano LIKE %s
        """

        cursor.execute(consulta, (f'%{plano}%',))
        resultados = cursor.fetchall()

        return resultados

    except Error as e:
        print("Erro ao conectar ao MySQL: ", e)
        return []
    finally:
        if conexao.is_connected():
            cursor.close()
            conexao.close()


def formatarDadosParaTexto(dados):
    if not dados:
        return "Não encontramos dados no relatório de movimentações."

    texto = "Aqui está a lista de movimentações do beneficiário:\n"
    for dado in dados:
        texto += f"- Carteirinha: {dado[0]}\n"
        texto += f"- Beneficiário: {dado[1]}\n"
        texto += f"- Matrícula: {dado[2]}\n"
        texto += f"- Plano: {dado[4]}\n"
        texto += f"- Titularidade: {dado[5]}\n"
        texto += f"- Status: {dado[10]}\n"
        texto += f"- Coparticipação: {dado[11]}\n"
        texto += f"- Outros gastos: {dado[12]}\n"
        texto += f"- Mensalidade: {dado[13]}\n"
        texto += f"- Mensalidade Família: {dado[14]}\n"
        texto += f"- Data de exclusão: {dado[15]}\n"

    return texto


def formatarDadosParaTextoRede(dados):
    print(f"DADOS ================ {dados}")

    if not dados:
        return "Não encontramos dados na rede. é de suma importancia informar a especialidade e o municipio buscado"

    if dados == "Informar a especialidade":
        return "Avise que é necessário informar a especialidade"

    if dados == "Hospital não encontrado":
        return "Avise ao usuario que o hospital buscado não faz parte da rede amil e que ele deve verificar com o responsavel"

    texto = "Aqui está a lista de prestadores de serviço encontrados:\n"
    for dado in dados:
        texto += f"- Nome do prestador: {dado[5]}\n"
        texto += f"- Plano inicial do hospital: {dado[1]}\n"
        texto += f"- Endereço: {dado[6]}\n"
        texto += f"- Número: {dado[7]}\n"
        texto += f"- Complemento: {dado[8]}\n"
        texto += f"- Bairro: {dado[9]}\n"
        texto += f"- CEP: {dado[10]}\n"
        texto += f"- Município: {dado[3]}\n"
        texto += f"- UF: {dado[2]}\n"
        texto += f"- Especialidade: {dado[4]}\n"
        texto += f"- DDD: {dado[11]}\n"
        texto += f"- Telefone: {dado[12]}\n"

    return texto


def formatarDadosParaTextoPlano(dados):
    if not dados:
        return "Não encontramos dados no relatório de planos."

    texto = "Aqui está a lista de planos encontrados:\n"
    for dado in dados:
        texto += f"- Nome do plano: {dado[4]}\n"
        texto += f"- Acomodação: {dado[1]}\n"
        texto += f"- Valor (custo médio): {dado[2]}\n"
        texto += f"- Operadora: {dado[3]}\n"
        texto += f"- Tipo de reembolso: {dado[5]}\n"

    return texto

    # def obterRedeBeneficiario(nome_beneficiario, especialidade, municipio):
    # Buscar plano do beneficiario
    plano = buscarPlanoBeneficiario(nome_beneficiario)
    if not plano:
        return f"Beneficiario {nome_beneficiario} não encontrado"

    redes = buscarRedePorEspecialidade(plano, especialidade, municipio)
    if not redes:
        return f"Nenhuma rede encontrada para {nome_beneficiario} na especialide {especialidade} e na cidade de {municipio}"

    return formatarDadosParaTextoRede(redes)


def buscarPlanoBeneficiario(mensagem):
    contexto = f"Dentro dessa mensagem {mensagem} Extraia apenas o nome da pessoa sem pontuação, lembre-se apenas o nome da pessoa, nada além disso"

    nome_beneficiario = gerarRepostaChatGPTSemHistórico(contexto, mensagem)

    print(f"NOME BENEFICIARIO ========= {nome_beneficiario}")

    try:
        conexao = mysql.connector.connect(
            host="localhost",
            port=3306,
            user="root",
            password="",
            database="w3g_movimentacoes"
        )

        cursor = conexao.cursor()

        consulta = """
            SELECT DISTINCT plano FROM movimentacoes
            WHERE beneficiario LIkE %s AND plano NOT LIKE %s
        """

        cursor.execute(consulta, (f'%{nome_beneficiario}%', '%DENTAL%'))
        resultado = cursor.fetchall()

        return resultado[0][0]

    except Error as e:
        print(f"Erro ao conectar ao MySQL {e}")
        return []
    finally:
        if conexao.is_connected():
            cursor.close()
            conexao.close()


def extrairCodigoPlano(plano):
    match = re.search(r'(\d+)', plano)
    if match:
        return int(match.group(1))  # Retorna o código como um número inteiro
    return None  # Retorna None se não encontrar


def buscarRedePorEspecialidade(mensagem):
    plano = buscarPlanoBeneficiario(mensagem)

    plano = extrairCodigoPlano(plano)

    print(f"PLANO ENCONTRADO =========== {plano}")

    print(f"PLANO ====== {plano}")

    contexto = f"Dentro dessa mensagem '{mensagem}' encontre qual é a especialidade informada, escreva apenas o nome da especialidade sem pontuação"

    especialidade = gerarRepostaChatGPTSemHistórico(contexto, mensagem)

    print(f"ESPECIALIDADE ======= {especialidade}")

    contexto = f"Dentro dessa mensagem '{mensagem}' encontre qual pe o municipio informado escreva apenas o municipio encontrado, sem nenhuma pontuacao e sem assento"

    municipio = gerarRepostaChatGPTSemHistórico(contexto, mensagem)

    print(f"MUNICIPIO ======== {municipio}")

    contexto_nome_hospital = f"""
        Dentro dessa mensagem: "{mensagem}", identifique qual é o hospital buscado na pergunta sem nenhuma pontuação. Lembre-se de escrever apenas o nome do hospital informada sem pontuação e sem assento. Pode acontecer de não possuir nenhum hospital nesse caso escreva 'desculpe'
    """
    nome_hospital = gerarRepostaChatGPTSemHistórico(contexto_nome_hospital, mensagem)

    try:
        conexao = mysql.connector.connect(
            host="localhost",
            port=3306,
            user="root",
            password="",
            database="w3g_movimentacoes"
        )

        cursor = conexao.cursor()

        if 'desculpe' in nome_hospital.lower():

            # Usando uma cláusula WHERE para verificar se o plano é menor ou igual ao plano máximo
            consulta = """
                SELECT * FROM redeamil
                WHERE elemento_de_divulgação LIKE %s
                AND numero_plano <= %s
                AND municipio LIKE %s
            """

            cursor.execute(consulta, (f'%{especialidade}%', plano, f'%{municipio}%'))
            resultados = cursor.fetchall()

            return resultados
        else:

            "consulta por hospital especifico"
            consulta = """
                SELECT * FROM redeAmil
                Where numero_plano <= %s
                and nome_prestador like %s
            """

            cursor.execute(consulta, (plano, f'%{nome_hospital}%'))
            resultados = cursor.fetchall()

            return resultados

    except Error as e:
        print(f"Erro ao conectar ao MySQL {e}")
        return []
    finally:
        if conexao.is_connected():
            cursor.close()
            conexao.close()


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)

