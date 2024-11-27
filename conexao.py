import mysql.connector
from mysql.connector import Error


def ChamarBancoDeDados():
    
    try:
        conexao = mysql.connector.connect(
            host="junction.proxy.rlwy.net",
            port=24650,
            user="root",
            password="yBsasCklOhhZnbeWRMvvwRQmWRLSoIkL",
            database="railway"
        )
                    
        return conexao
    
    except Error as e:
        print(f"Erro ao conectar ao MySQL: {e}")
        return []

        