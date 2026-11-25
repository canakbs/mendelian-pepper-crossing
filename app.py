import os
from wsgiref import headers
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, jsonify
import pandas as pd
import numpy as np
import re
import uuid

app = Flask(__name__)
app.secret_key = 'biber_es_bulma_secret_key_2024'

# Hibrit analiz metodları - Mendel kanunlarına dayalı bilimsel yaklaşım

def normalize_genotip(genotip):
    """Genotip değerlerini standartlaştır"""
    if pd.isna(genotip) or genotip in ['NTC', '?', 'NT']:
        return 'NT'
    
    genotip = str(genotip).upper().strip()
    
    genotip_mapping = {
        'HT': 'Ht',
        'HETEROZIGOT': 'Ht',
        'HETEROZYOT': 'Ht',
        'RESISTANT': 'R',
        'SUSCEPTIBLE': 'S',
        'HASSAS': 'S',
        'DİRENÇLİ': 'R'
    }
    
    return genotip_mapping.get(genotip, genotip)

def tahmin_et_hibrit_direnç(anne_genotip, baba_genotip):
    anne = normalize_genotip(anne_genotip)
    baba = normalize_genotip(baba_genotip)
    
    if anne == 'NT' or baba == 'NT':
        return {
            'hibrit_genotip': 'NT',
            'dominant_prob': 0,
            'heterozigot_prob': 0,
            'resesif_prob': 0,
            'güven_skoru': 0.0
        }
    
    hibrit_matris = {
        ('R', 'R'): {'genotip': 'R', 'dominant': 100, 'heterozigot': 0, 'resesif': 0, 'güven': 1.0},
        ('R', 'Ht'): {'genotip': 'R/Ht', 'dominant': 75, 'heterozigot': 25, 'resesif': 0, 'güven': 0.9},
        ('R', 'S'): {'genotip': 'Ht', 'dominant': 50, 'heterozigot': 50, 'resesif': 0, 'güven': 1.0},
        ('Ht', 'R'): {'genotip': 'R/Ht', 'dominant': 75, 'heterozigot': 25, 'resesif': 0, 'güven': 0.9},
        ('Ht', 'Ht'): {'genotip': 'R/Ht/S', 'dominant': 25, 'heterozigot': 50, 'resesif': 25, 'güven': 0.8},
        ('Ht', 'S'): {'genotip': 'Ht/S', 'dominant': 0, 'heterozigot': 50, 'resesif': 50, 'güven': 0.9},
        ('S', 'R'): {'genotip': 'Ht', 'dominant': 50, 'heterozigot': 50, 'resesif': 0, 'güven': 1.0},
        ('S', 'Ht'): {'genotip': 'Ht/S', 'dominant': 0, 'heterozigot': 50, 'resesif': 50, 'güven': 0.9},
        ('S', 'S'): {'genotip': 'S', 'dominant': 0, 'heterozigot': 0, 'resesif': 100, 'güven': 1.0}
    }
    
    key = (anne, baba)
    if key in hibrit_matris:
        sonuç = hibrit_matris[key]
    else:
        key_reverse = (baba, anne)
        if key_reverse in hibrit_matris:
            sonuç = hibrit_matris[key_reverse]
        else:
            sonuç = {'genotip': f'{anne}/{baba}', 'dominant': 33, 'heterozigot': 34, 'resesif': 33, 'güven': 0.5}
    
    return {
        'hibrit_genotip': sonuç['genotip'],
        'dominant_prob': sonuç['dominant'],
        'heterozigot_prob': sonuç['heterozigot'],
        'resesif_prob': sonuç['resesif'],
        'güven_skoru': sonuç['güven']
    }

def hesapla_hibrit_skor(hibrit_tahmin, scoring_method):
    if scoring_method == '1':
        R_AĞIRLIK, HT_AĞIRLIK, S_AĞIRLIK = 1.0, 1.0, 0.0
    else:
        R_AĞIRLIK, HT_AĞIRLIK, S_AĞIRLIK = 0.7, 1.0, 0.0
    
    skor = (
        (hibrit_tahmin['dominant_prob'] / 100) * R_AĞIRLIK +
        (hibrit_tahmin['heterozigot_prob'] / 100) * HT_AĞIRLIK +
        (hibrit_tahmin['resesif_prob'] / 100) * S_AĞIRLIK
    )
    
    final_skor = skor * hibrit_tahmin['güven_skoru']
    
    return final_skor

def load_data(uploaded_file_path=None):
    try:
        if uploaded_file_path:
            df = pd.read_excel(uploaded_file_path)
        else:
            raise Exception("Lütfen analiz için bir Excel dosyası yükleyin.")
        if 'Unnamed: 1' in df.columns:
            df = df.rename(columns={'Unnamed: 1': 'ID'})
        df = df.dropna(subset=[df.columns[0]])
        df.reset_index(drop=True, inplace=True)
        for col in df.columns:
            if col != 'ID':
                df[col] = df[col].apply(normalize_genotip)
        return df
    except Exception as e:
        raise Exception(f"Veri yükleme hatası: {str(e)}")

# YENİ VEKTÖRLEŞTİRİLMİŞ ÇAPRAZLAMA FONKSİYONU
def calculate_scores_vectorized(anne_df, df, scoring_method, cross_columns):
    # 1. Tüm olası anne-baba kombinasyonlarını oluştur
    anne_df['key'] = 1
    df['key'] = 1
    combined = pd.merge(anne_df, df, on='key', suffixes=('_anne', '_baba'))
    anne_df.drop('key', axis=1, inplace=True)
    df.drop('key', axis=1, inplace=True)
    combined.drop('key', axis=1, inplace=True)
    
    # 2. Kendi kendine çaprazlamaları filtrele
    combined = combined[combined['ID_anne'] != combined['ID_baba']]
    
    # 3. Her gen için hibrit tahmini ve skor hesapla
    combined['total_score'] = 0.0
    hibrit_detay_df = pd.DataFrame()
    
    for col in cross_columns:
        anne_col = col + '_anne'
        baba_col = col + '_baba'
        
        # Hibrit tahminleri hesapla
        combined[col + '_hibrit'] = combined.apply(
            lambda row: tahmin_et_hibrit_direnç(row[anne_col], row[baba_col]), 
            axis=1
        )
        
        # Hibrit skorlarını hesapla
        combined[col + '_skor'] = combined[col + '_hibrit'].apply(
            lambda x: hesapla_hibrit_skor(x, scoring_method)
        )
        
        # Toplam skora ekle
        combined['total_score'] += combined[col + '_skor']
        
        # Hibrit detayları için geçici DataFrame oluştur
        temp_df = combined[['ID_anne', 'ID_baba', col + '_hibrit', col + '_skor']].copy()
        temp_df.rename(columns={
            col + '_hibrit': 'hibrit',
            col + '_skor': 'skor'
        }, inplace=True)
        temp_df['gen'] = col
        
        # Ana hibrit detay DataFrame'ine ekle
        hibrit_detay_df = pd.concat([hibrit_detay_df, temp_df])
    
    # 4. Her anne için en iyi 5 baba seç
    top5_per_anne = combined.groupby('ID_anne').apply(
        lambda x: x.nlargest(5, 'total_score')
    ).reset_index(drop=True)
    
    # 5. Sonuçları formatla
    results = []
    for _, row in top5_per_anne.iterrows():
        anne_id = row['ID_anne']
        baba_id = row['ID_baba']
        total_score = row['total_score']
        
        # Hibrit detayları için filtrele
        hibrit_detayları = {}
        for col in cross_columns:
            detay = hibrit_detay_df[
                (hibrit_detay_df['ID_anne'] == anne_id) & 
                (hibrit_detay_df['ID_baba'] == baba_id) &
                (hibrit_detay_df['gen'] == col)
            ].iloc[0]
            
            h = detay['hibrit']
            hibrit_detayları[col] = {
                'hibrit_genotip': h['hibrit_genotip'],
                'dominant_prob': h['dominant_prob'],
                'heterozigot_prob': h['heterozigot_prob'],
                'resesif_prob': h['resesif_prob'],
                'güven_skoru': round(h['güven_skoru'] * 100),
                'gen_skor': round(detay['skor'], 3)
            }
        
        aday_data = {
            'anne_id': anne_id,
            'baba_id': baba_id,
            'hibrit_detaylar': hibrit_detayları,
            'score': total_score
        }
        
        # Anne ve baba genotiplerini ekle
        for col in cross_columns:
            aday_data[f'anne_{col}'] = row[col + '_anne']
            aday_data[f'baba_{col}'] = row[col + '_baba']
        
        results.append(aday_data)
    
    # Baba sıralamasını ekle
    for result in results:
        anne_id = result['anne_id']
        anne_results = [r for r in results if r['anne_id'] == anne_id]
        sorted_anne_results = sorted(anne_results, key=lambda x: x['score'], reverse=True)
        for rank, res in enumerate(sorted_anne_results, 1):
            if res['baba_id'] == result['baba_id']:
                result['baba_rank'] = rank
                break
    
    return results

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            uploaded_file = request.files.get('excel_file')
            if uploaded_file and uploaded_file.filename.endswith('.xlsx'):
                storage_dir = os.path.join(os.path.dirname(__file__), 'storage')
                if not os.path.exists(storage_dir):
                    os.makedirs(storage_dir)
                unique_name = f"{uuid.uuid4().hex}_{uploaded_file.filename}"
                file_path = os.path.join(storage_dir, unique_name)
                uploaded_file.save(file_path)
                df = load_data(file_path)
            else:
                flash("Lütfen analiz için bir Excel dosyası yükleyin.", 'error')
                return render_template('index.html', total_records=0)
            
            scoring_method = request.form.get('scoring_method', '1')
            anne_tm0 = request.form.get('anne_tm0', '').strip().upper()
            anne_tm2 = request.form.get('anne_tm2', '').strip().upper()
            anne_tswv = request.form.get('anne_tswv', '').strip().upper()
            
            dynamic_filters = {}
            dynamic_pattern = re.compile(r'^dynamic_(.+)$')
            for key in request.form:
                match = dynamic_pattern.match(key)
                if match:
                    col = match.group(1)
                    val = request.form[key].strip().upper()
                    if val and val not in ['YOK', 'NT', '?', '']:
                        dynamic_filters[col] = val
            
            anne_tm0 = normalize_genotip(anne_tm0) if anne_tm0 else ''
            anne_tm2 = normalize_genotip(anne_tm2) if anne_tm2 else ''
            anne_tswv = normalize_genotip(anne_tswv) if anne_tswv else ''
            for k in dynamic_filters:
                dynamic_filters[k] = normalize_genotip(dynamic_filters[k])
            
            anne_df = df.copy()
            valid_genotypes = ['R', 'Ht', 'S', 'RR', 'Rr', 'rr']
            if anne_tm0 in valid_genotypes:
                anne_df = anne_df[anne_df['Tm0(L1)'] == anne_tm0]
            if anne_tm2 in valid_genotypes:
                anne_df = anne_df[anne_df['Tm2(L3)'] == anne_tm2]
            if anne_tswv in valid_genotypes:
                anne_df = anne_df[anne_df['Tswv'] == anne_tswv]
            for col, val in dynamic_filters.items():
                if col in anne_df.columns and val in valid_genotypes:
                    anne_df = anne_df[anne_df[col] == val]
            
            selected_columns = []
            if anne_tm0 in valid_genotypes:
                selected_columns.append('Tm0(L1)')
            if anne_tm2 in valid_genotypes:
                selected_columns.append('Tm2(L3)')
            if anne_tswv in valid_genotypes:
                selected_columns.append('Tswv')
            for col in dynamic_filters:
                if col in df.columns:
                    selected_columns.append(col)
            selected_columns = list(dict.fromkeys(selected_columns))
            if anne_df.empty or not selected_columns:
                flash("Seçilen filtrelere uyan hiçbir anne adayı bulunamadı veya anlamlı gen seçilmedi.", 'warning')
                return render_template('index.html', total_records=len(df))
            else:
                # YENİ VEKTÖRLEŞTİRİLMİŞ FONKSİYON KULLANIMI
                results = calculate_scores_vectorized(anne_df, df, scoring_method, selected_columns)
                
                selected_features = []
                if anne_tm0 in valid_genotypes:
                    selected_features.append(('Tm0(L1)', anne_tm0))
                if anne_tm2 in valid_genotypes:
                    selected_features.append(('Tm2(L3)', anne_tm2))
                if anne_tswv in valid_genotypes:
                    selected_features.append(('Tswv', anne_tswv))
                for col, val in dynamic_filters.items():
                    selected_features.append((col, val))
                return render_template('results.html', 
                                     results=results, 
                                     total_records=len(df), 
                                     filtered_records=len(anne_df),
                                     hibrit_mode=True,
                                     selected_features=selected_features,
                                     analyzed_genotypes_columns=selected_columns)
        except Exception as e:
            flash(f'Hata: {str(e)}', 'error')
            return render_template('index.html')
    
    return render_template('index.html', total_records=0)

@app.route('/download-excel')
def download_excel():
    try:
        excel_file_path = os.path.join(os.path.dirname(__file__), "YAPAY ZEKA MODELLEME MARKIR  SONUÇ 1 RENKLI.xlsx")
        
        if not os.path.exists(excel_file_path):
            flash("Excel dosyası bulunamadı.", 'error')
            return redirect(url_for('index'))
        
        return send_file(
            excel_file_path,
            as_attachment=True,
            download_name="biber_hibrit_veri.xlsx",
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        flash(f'Dosya indirme hatası: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/get_headers', methods=['POST'])
def get_headers():
    if 'excel_file' not in request.files:
        return jsonify({'error': 'Dosya bulunamadı'}), 400

    file = request.files['excel_file']
    if not file.filename.endswith('.xlsx'):
        return jsonify({'error': 'Sadece .xlsx dosyası yükleyebilirsiniz'}), 400

    try:
        df = pd.read_excel(file, nrows=0)
        headers = [h for h in df.columns if h.lower() != "remark"]
        return jsonify({'headers': headers})    
    except pd.errors.EmptyDataError:
        return jsonify({'error': 'Yüklenen Excel dosyası boş veya okunamadı. Lütfen geçerli bir dosya yükleyin.'}), 400
    except Exception as e:
        return jsonify({'error': f'Dosya okunurken bir hata oluştu: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)