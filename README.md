# Sentinela

Confere de fora do servidor, a cada 5 minutos, se a plataforma responde. Duas falhas seguidas avisam o celular; a volta avisa de novo. O aviso sai pelo ntfy e não depende do servidor conferido.

- `sentinela.py`: a conferência e a decisão de avisar.
- `.github/workflows/sentinela.yml`: o agendamento.
- `testes/testar.py`: a bateria (`python testes/testar.py`).
- `teste/`: alvo de teste, usado só enquanto `teste/ATIVO` existir. Os avisos dele começam com "TESTE".

O canal do aviso fica no segredo `NTFY_TOPICO` do repositório, nunca no código.
