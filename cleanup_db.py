import sqlite3

conn = sqlite3.connect('data/recession_kpi.db')
for kpi in ['copper_price', 'cfnai', 'rail_carloads', 'silver_price', 'gdp_growth']:
    conn.execute("DELETE FROM kpi_data WHERE kpi_id = ?", (kpi,))
    print(f'Deleted {kpi}')
conn.commit()
conn.close()
print('Done')
