content = open('/root/pump_executor.py').read()

old = '            except: pass\n                buy_price = (amount_sol * sol_price) / token_amount if token_amount > 0 else 0'

new = '            except: pass\n            buy_price = (amount_sol * sol_price) / token_amount if token_amount > 0 else 0'

if old in content:
    content = content.replace(old, new)
    open('/root/pump_executor.py', 'w').write(content)
    print("✅ Indent fixed")
else:
    print("❌ not found")
