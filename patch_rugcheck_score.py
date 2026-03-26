content = open('/root/auto_trader.py').read()

old = '''    rug_match = re.search(r'Rugcheck: ([\d,]+)/1000', text)
    if rug_match:
        rug = int(rug_match.group(1).replace(',', ''))
        if rug > 5000: score -= 25
        elif rug > 1000: score -= 10
        elif rug <= 500: score += 5'''

new = '''    rug_match = re.search(r'Rugcheck: ([\d,]+)/1000', text)
    if rug_match:
        rug = int(rug_match.group(1).replace(',', ''))
        # Rugcheck: score TINGGI = AMAN, score RENDAH = BANYAK ISSUE
        if rug >= 700: score += 10
        elif rug >= 400: score += 5
        elif rug < 200: score -= 20
        elif rug < 400: score -= 10'''

if old in content:
    content = content.replace(old, new)
    open('/root/auto_trader.py', 'w').write(content)
    print("✅ Rugcheck logic fixed!")
else:
    print("❌ pattern not found")
    idx = content.find("rug > 5000")
    print("Context:", repr(content[idx-100:idx+100]))
