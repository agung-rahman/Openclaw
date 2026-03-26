content = open('/root/position_monitor_v2.py').read()

old = '''                                        if not result.get("success"):
                                            _bal_after = await get_token_balance(mint)'''

new = '''                                        if not result.get("success"):
                                            _bal_after = await _gtb(mint)'''

if old in content:
    content = content.replace(old, new)
    open('/root/position_monitor_v2.py', 'w').write(content)
    print("✅ NameError fix done")
else:
    print("❌ pattern not found")
    idx = content.find("get_token_balance(mint)")
    print("All occurrences:")
    import re
    for m in re.finditer(r'.{0,50}get_token_balance\(mint\).{0,50}', content):
        print(repr(m.group()))
