# 05 — API-контракт и форматы данных

Базовый префикс: `/api/v1/attenuator2`. Совместим по стилю с существующим
`backend/api/routers/attenuator.py` в `tydex-products-toolkits` (ADR_005 — версионирование API).

---

## 1. Паспорт калибровки прибора

Центральный артефакт. Всё остальное — функции от него. Хранение:
`backend/data/calibrations/<serial>/passport.json` (каталог уже существует в продукте).

```jsonc
{
  "schema_version": "1.0",
  "device": {
    "serial": "ATT-11-16-CA85-SAMPLE",
    "model": "TGC-W16",
    "aperture_mm": 25.4,
    "nominal": { "P_um": 16.0, "D_um": 5.5, "material": "W" }
  },

  // ── ЧТО ПОДОГНАНО ─────────────────────────────────────────────────────────
  "fit": {
    "band_thz": [0.20, 1.50],            // ПОЛОСА КАЛИБРОВКИ — граница экстраполяции
    "scheme": "S3",                       // в какой схеме снимались данные (03 §4!)
    "detector": "coherent",               // coherent | power
    "n_angles": 13, "n_reps": 4, "n_points": 1495,
    "method": "weighted_lmfit_leastsq",   // t20_weighted_fit.py
    "date": "2026-07-27",
    "redchi": 1.83, "aic": -22680.4
  },

  // ── ПАРАМЕТРЫ МОДЕЛИ: ЕДИНЫЙ НАБОР, НЕ НЕЗАВИСИМЫЕ ВЕЛИЧИНЫ ───────────────
  "params": {
    "P_um":         { "value": 15.50, "stderr": 0.00, "fixed": true,
                      "note": "закреплён оптическим контролем" },
    "D_eff_um":     { "value":  4.68, "stderr": 0.31 },
    "loss_factor":  { "value":  0.255, "stderr": 0.02, "units": "dB/THz^gamma" },
    "gamma":        { "value":  1.58, "stderr": 0.40, "range": [0.9, 2.1],
                      "identifiable": false,
                      "note": "вырожден с утечкой; range -> огибающая экстраполяции" },
    "eta0":         { "value":  0.021, "stderr": 0.013 },
    "eta_exp":      { "value":  1.00, "fixed": true },
    "delta0_rad":   { "value":  0.00, "stderr": 0.31 },
    "tau_leak_ps":  { "value":  0.192, "stderr": 0.06 },
    "tau_par_ps":   { "value":  0.00, "stderr": 0.02 },
    "theta_offset_deg": { "value": -0.45, "stderr": 0.20 }
  },
  "covariance": {                          // ОБЯЗАТЕЛЬНА: параметры вырождены
    "order": ["D_eff_um","loss_factor","gamma","eta0","tau_leak_ps","theta_offset_deg"],
    "matrix": [[ /* 6x6 */ ]]
  },

  // ── ПРОИЗВОДНЫЕ ХАРАКТЕРИСТИКИ (для витрины и быстрых проверок) ───────────
  "derived": {
    "D_eff_over_D_phys": 0.43,
    "nu_anomaly_thz": 19.35,               // c / P
    "zone_green_max_thz": 3.22,            // nu_anomaly / 6
    "zone_red_min_thz": 12.90,             // nu_anomaly / 1.5
    "extinction_ratio_at_1thz_db": 33.6,
    "insertion_loss_at_1thz_db": 0.53,     // |t_perp|^4
    "attenuation_floor_db": 34.8,
    "theta_extinction_deg": 84.1           // ИЗМЕРЕННЫЙ минимум, не 90
  },

  "provenance": {
    "raw_data": ["specac_84deg_rep1_sig.txt", "..."],
    "core_version": "thz_atten_core 0.1.0",
    "git_commit": "…",
    "operator": "…"
  }
}
```

**Инварианты паспорта, проверяемые при загрузке:**

- `fit.band_thz` — обязательно; без него экстраполяция не может быть отмечена как таковая;
- `covariance` — обязательна, если хоть один параметр не `fixed`. Причина: `D_eff ↔ η`
  вырождены с корреляцией ±1.0, показывать их как независимые значения — научная ошибка;
- `gamma.range` — обязателен, если `identifiable: false`; из него строится огибающая
  экстраполяции;
- `derived.theta_extinction_deg` — из данных, **никогда не литерал 90**;
- `fit.scheme` — параметры, подогнанные в схеме S3, помечаются при использовании в S1/S2
  предупреждением (см. `03_OPTICAL_SCHEMES.md` §4).

---

## 2. Эндпоинты

### 2.1. `POST /forward` — прямая задача

```jsonc
// запрос
{
  "passport_ref": "ATT-11-16-CA85-SAMPLE@1.0",
  "scheme": "S1",
  "geometry": { "theta1_deg": 71.6, "theta2_deg": 0.0,
                "psi_deg": 0.0, "det_deg": 0.0, "phi2_minus_d_deg": 0.0 },
  "input_state": { "S0": 1.0, "dop": 1.0, "azimuth_deg": 0.0, "ellipticity_deg": 0.0 },
  "reference_mode": "zero_angle",            // input | zero_angle | external
  "zero_ref": { "theta1_deg": 0.0, "theta2_deg": 0.0, "timestamp": "…" },
  "detector": "coherent",
  "output": {
    "spectral": { "f_min_thz": 0.05, "f_max_thz": 6.0, "n": 512 },
    "integral": { "weight": { "kind": "bg_file", "id": "up-2026-07-27-a1" } }
  }
}
```

```jsonc
// ответ
{
  "spectral": {
    "freq_thz":  [...],
    "att_db":    [...],
    "sigma_db":  [...],
    "core_only_db": [...],                  // только Бланко+Друде, без феноменологии
    "gamma_envelope_db": [[lo],[hi]],
    "zone":      ["green","green","amber",...],
    "extrapolated": [false,false,true,...],
    "dressing_clipped": [false,...],
    "azimuth_out_deg": [...], "ellipticity_out_deg": [...]
  },
  "integral": {
    "att_db": 20.4, "sigma_db": 0.6,
    "weight": { "kind": "bg_file", "id": "…", "effective_band_thz": [0.21, 2.05] },
    "ideal_cos4_db": 20.0,
    "spectral_spread_db": 1.7               // размах A(nu) по эффективной полосе -> F5
  },
  "calibration_band_thz": [0.20, 1.50],
  "warnings": [ { "code": "F5", "severity": "warn",
                  "message": "Неравномерность 1.7 дБ p-p в 0.21-2.05 ТГц" } ]
}
```

### 2.2. `POST /inverse` — обратная задача

```jsonc
// запрос
{
  "passport_ref": "…", "scheme": "S1",
  "target": { "metric": "relative_db", "value": 20.0,
              "at": { "kind": "integral", "weight": {...} } },   // или {"kind":"freq","freq_thz":1.0}
  "reference_mode": "zero_angle", "zero_ref": {...},
  "current": { "theta1_deg": 0.0, "theta2_deg": 0.0 },
  "rotator": { "step_deg": 0.05, "backlash_deg": 0.1,
               "repeatability_deg": 0.02, "range_deg": [-180, 180] },
  "tolerances": { "sigma_db": 0.5, "spectral_spread_db": 1.0,
                  "azimuth_deg": 2.0, "dr_margin_db": 6.0 },
  "policy": "monotone_branch_then_precision"
}
```

```jsonc
// ответ — успех
{
  "feasible": true,
  "solutions": [
    { "theta1_deg": 71.63, "theta2_deg": 0.0, "rank": 1, "branch": "monotone",
      "achieved_db": 20.00, "sigma_db": 0.31,
      "sigma_breakdown": { "model": 0.18, "rotator_step": 0.05,
                           "backlash": 0.09, "repeatability": 0.02 },
      "dA_dtheta_db_per_deg": 0.91,
      "move_deg": 71.63, "flags": [] },
    { "theta1_deg": -71.63, "rank": 2, "branch": "mirror", "...": "..." }
  ],
  "limits": { "attenuation_floor_db": 34.8, "at_theta_deg": 84.1,
              "dynamic_range_db": 41.2, "limited_by": "leakage_floor" }
}
```

```jsonc
// ответ — отказ (F1..F8), см. 02_SCENARIOS.md §4
{
  "feasible": false,
  "failed": [
    { "code": "F2", "message": "Цель 45 дБ выше пола прибора 34.8 дБ" },
    { "code": "F4", "message": "На 40 дБ шаг 1° даёт σ=3.0 дБ (допуск 0.5). Нужен шаг ≤ 0.17°" }
  ],
  "achievable_max_db": 34.8, "achievable_at_deg": 84.1,
  "suggestions": [
    { "action": "add_si_wafer", "gain_db": 3.01, "cost": "эхо T_win=12 пс, Δf=0.084 ТГц" },
    { "action": "finer_rotator", "required_step_deg": 0.17 },
    { "action": "narrow_band", "band_thz": [0.3, 1.2] }
  ]
}
```

### 2.3. Остальные

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/passports` | список паспортов с `derived` для витрины |
| `POST` | `/passports` | загрузить/сохранить паспорт; валидация инвариантов §1 |
| `POST` | `/calibrate` | измерения → фит → черновик паспорта + ковариация + bootstrap |
| `POST` | `/zero` | `set` (текущее) \| `auto_max` \| `auto_cross` → `zero_ref` + `θ_offset` |
| `POST` | `/map` | `A(θ₁,θ₂)` на сетке (тепловая карта, только S2) |
| `POST` | `/sweep` | развёртка уровней S-8: список целей → таблица углов, монотонный обход |
| `POST` | `/diagnose` | S-11: ER, `θ_offset`, отклонение от `cos⁴`, `\|θ_min−θ_max\|−90°` |
| `POST` | `/verify` | сравнить предсказание с измеренной точкой; `residual_db`, `z-score` |
| `POST` | `/upload/tds` | загрузка `sig/bg/dark`, FFT, усреднение повторов, `DR(ν)` |
| `GET` | `/weights/presets` | пресеты источников (LiNbO₃, орг. кристалл, плазма, PCA) |
| `GET` | `/schemes` | описания S1…S8 + какие поля геометрии обязательны |
| `POST` | `/report` | протокол PDF/CSV/JSON |

---

## 3. Формат входных измерений

### 3.1. Поддерживаемые схемы имён

Приложение должно принимать **оба поколения**, встречающиеся в этом рабочем пространстве:

| Формат | Пример | Откуда |
|---|---|---|
| `{dataset}_{angle}deg_rep{N}_{sig\|bg}.txt` | `specac_84deg_rep2_sig.txt` | `THz-Unified-Optimizer/data_pool/` (основной) |
| `{a1}-{a2}-{rep}-{bg_name}.txt` + `bg_{N}.txt` | `10-0-2-bg_7.txt` | `THz-Spectroscopy-Python-Manual2/src/data/` |
| `{angle}_bg{ID}.txt` | `45_bg1.txt` | Attenuator Studio (существующий продукт) |

Плюс явный маппинг вручную через UI, когда автоопределение не сработало. Содержимое —
две колонки: время (пс) и поле (отн. ед.), пробельный разделитель.

Отдельно — **dark** (перекрытый пучок): вычитается и из `sig`, и из `bg` (так делает
существующий продукт) и используется как один из двух способов оценки `DR`.

### 3.2. Обработка

1. вычитание `dark`; вычитание постоянной составляющей по первым отсчётам;
2. FFT с дополнением нулями (padding ×4 — как в существующем продукте, даёт гладкий спектр);
3. комплексное пропускание `T(ν) = E_sig(ν) / E_bg(ν)` (**комплексное**, амплитуда + фаза);
4. группировка и усреднение повторов; per-точка `σ` по повторам → веса фита
   (реализовано в `research/experiments/t20_weighted_fit.py`);
5. автомаска линий воды — скользящее окно, отсев выбросов
   (`unified_optimizer/utils.py:find_auto_water_mask`);
6. `DR(ν)` по ВЧ-хвосту фона (`ν ≥ 3 ТГц`).

---

## 4. Экспорт

### 4.1. CSV спектра

```csv
# device=ATT-11-16-CA85-SAMPLE  passport=1.0  scheme=S1  mode=relative
# zero_ref=2026-07-27T10:22:31Z theta1_0=0.00 theta2_0=0.00
# calibration_band_thz=0.20..1.50  detector=coherent  weight=bg_file:up-...
freq_thz,att_db,sigma_db,core_only_db,gamma_lo_db,gamma_hi_db,zone,extrapolated
0.100,20.02,0.09,20.01,20.00,20.03,green,true
...
```

Заголовочные комментарии обязательны: без `zero_ref`, `calibration_band_thz` и
`passport` число в дБ не интерпретируемо задним числом.

### 4.2. JSON протокола

Полная запись сессии: паспорт (по ссылке + хэш), схема, все `zero_ref`, каждый запрос
и ответ с временными метками, версия ядра, git-commit. Это то, что прикладывается к
результатам эксперимента и к паспорту прибора при поставке.

### 4.3. PDF-отчёт

Тот же генератор, что уже используется в этом репозитории (`reportlab`, кириллица через
Arial — см. `scripts/compile_pdf_specification.py`, `research/experiments/make_experiment_pdf.py`).
Состав: сводка прибора, кривые `A(ν)` и `A(θ)` с коридорами, таблица уровней, все флаги
F1…F8, честный раздел «границы применимости».

---

## 5. Коды ошибок

| Код | HTTP | Смысл |
|---|---|---|
| `PASSPORT_NOT_FOUND` | 404 | нет такого паспорта/версии |
| `PASSPORT_INVALID` | 422 | нарушен инвариант §1 (нет `band_thz` / нет ковариации при свободных параметрах) |
| `SCHEME_FIELDS_MISSING` | 422 | для выбранной схемы не заданы обязательные углы (`03` §9) |
| `WEIGHT_REQUIRED` | 422 | запрошено интегральное затухание без `w(ν)` |
| `FREQ_OUT_OF_PHYSICAL_RANGE` | 422 | `ν ≥ ν_anom/1.5` — красная зона, число не выдаётся |
| `INFEASIBLE` | 200 | обратная задача: `feasible: false` + разбор (это **не** ошибка HTTP) |
| `NO_DYNAMIC_RANGE_DATA` | 200 | проверка F3 пропущена, помечено в ответе |

Отдельно подчёркнуто: **недостижимая цель — не HTTP-ошибка**. Это штатный, информативный
результат с максимумом достижимого и списком средств. Молчаливый возврат ближайшего угла
без пометки — главный антипаттерн, которого этот проект избегает.
