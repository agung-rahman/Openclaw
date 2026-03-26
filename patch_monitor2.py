content = open('/root/position_monitor_v2.py').read()

old = '''                                        result = await sell(mint, 100, symbol)
                                        if result.get("succes'''

# Cari full pattern yang exact
idx = content.find('                                        result = await sell(mint, 100, symbol)')
print(f"idx: {idx}")
print("Context 300 chars:")
print(repr(content[idx-50:idx+250]))
