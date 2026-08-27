"""Паспорт прибора: калибровочные параметры + метрология шкалы.

Паспорт — единственный источник истины о конкретном экземпляре аттенюатора.
Всё остальное в приложении — функции от него.

Неопределённости параметров берутся НЕ из ковариации одного фита, а из
воспроизводимости между независимыми сеансами калибровки: формальные stderr
одного фита занижены примерно в 25 раз (D_eff: stderr 0.01 мкм против разброса
0.25 мкм между четырьмя сеансами одного и того же прибора). Это сознательное
занижение точности ради надёжного покрытия 95%.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

C_LIGHT_UM_THZ = 3e8 * 1e6 / 1e12      # мкм·ТГц = 3e2


@dataclass
class Param:
    """Параметр модели: значение + консервативная 1σ."""
    value: float
    sigma: float = 0.0
    source: str = ""            # 'session_spread' | 'fit_cov' | 'prior' | 'fixed'

    def draw_bounds(self, k: float = 1.96) -> tuple[float, float]:
        return self.value - k * self.sigma, self.value + k * self.sigma


@dataclass
class ScaleSpec:
    """Метрология угловой шкалы (ручная установка угла)."""
    division_deg: float = 2.0        # цена деления
    zero_set_deg: float | None = None  # погрешность выставления нуля; None -> division/2

    def sigma_read_deg(self) -> float:
        """Консервативная 1σ отсчёта по шкале.

        Для равномерного распределения в пределах деления σ = d/√12 ≈ 0.29d.
        Берём d/2 — завышение неопределённости в 1.7 раза (сознательно).
        """
        return self.division_deg / 2.0

    def sigma_zero_deg(self) -> float:
        return self.zero_set_deg if self.zero_set_deg is not None else self.division_deg / 2.0

    def sigma_total_deg(self) -> float:
        """Полная 1σ угла: отсчёт + установка нуля, квадратично."""
        return float(np.hypot(self.sigma_read_deg(), self.sigma_zero_deg()))


@dataclass
class FilmPolarizer:
    """Плёночный поляризатор (полипропилен, Tydex).

    K1 — пропускание полезной поляризации, K2 — нежелательной, доли единицы.
    Оба частотно-зависимы ступенчато: спека Tydex даёт две полосы,
    250-3000 мкм (0.10-1.20 ТГц) и 15-250 мкм (1.20-20 ТГц).
    """
    name: str = "Tydex film D25-45"
    K1: float = 0.80
    K2_low_band: float = 2.0e-4        # <0.02 % при 250-3000 мкм
    K2_high_band: float = 3.0e-3       # <0.3 %  при 15-250 мкм
    band_split_thz: float = 1.20       # 250 мкм
    lines_per_mm: float = 1200.0

    def k2(self, freqs_thz) -> np.ndarray:
        nu = np.asarray(freqs_thz, dtype=float)
        return np.where(nu <= self.band_split_thz, self.K2_low_band, self.K2_high_band)

    def amps(self, freqs_thz):
        """Амплитудные коэффициенты (по оси пропускания, по ортогональной)."""
        return np.sqrt(self.K1), np.sqrt(self.k2(freqs_thz))

    def er_db(self, freqs_thz) -> np.ndarray:
        return 10.0 * np.log10(self.K1 / self.k2(freqs_thz))


@dataclass
class Passport:
    serial: str = "UNKNOWN"
    model: str = ""
    aperture_mm: float = 25.0

    # --- геометрия решётки ---
    P_um: Param = field(default_factory=lambda: Param(15.5, 0.0, "fixed"))
    D_eff_um: Param = field(default_factory=lambda: Param(4.48, 0.25, "session_spread"))
    D_phys_um: float = 11.0

    # --- феноменология ---
    loss_factor: Param = field(default_factory=lambda: Param(0.338, 0.142, "session_spread"))
    gamma: Param = field(default_factory=lambda: Param(2.0, 0.0, "fixed"))
    gamma_range: tuple = (1.0, 3.0)
    eta0: Param = field(default_factory=lambda: Param(0.0, 0.0, "fixed"))
    eta_exp: float = 1.0
    delta0: float = 0.0
    tau_leak_ps: Param = field(default_factory=lambda: Param(0.0, 0.0, "fixed"))
    tau_ps: Param = field(default_factory=lambda: Param(0.033, 0.011, "session_spread"))
    tau_par_ps: Param = field(default_factory=lambda: Param(-0.097, 0.032, "session_spread"))
    angle_offset_deg: Param = field(default_factory=lambda: Param(-0.09, 0.96, "session_spread"))

    # Идеализация элементов: t_perp = 1, t_par = 0. Нужна для эталонной кривой
    # cos^4 и для приёмочных тестов. У РЕАЛЬНОЙ решётки так не бывает: модель
    # Бланко даёт максимум экстинкции при D_eff около 4.5 мкм (P = 15.5), а не
    # при D -> 0 (тонкая проволока почти прозрачна для обеих поляризаций) и не
    # при D -> P. Это же и объясняет, куда фит уводит D_eff.
    ideal_elements: bool = False

    # --- условия калибровки ---
    band_thz: tuple = (0.20, 1.50)
    fit_scheme: str = "S0"
    fit_detector: str = "coherent"
    calibration_note: str = ""
    datasets: tuple = ()
    # Паспортная RMSE аппроксимации модели: независимый вклад в неопределённость,
    # который НЕ выводится из ковариации параметров (неучтённые переотражения
    # между решётками и дифракционное рассеяние на больших углах).
    model_rmse_db: float = 0.0
    model_rmse_note: str = ""

    # --- метрология и оснастка ---
    scale: ScaleSpec = field(default_factory=ScaleSpec)
    film: FilmPolarizer | None = field(default_factory=FilmPolarizer)

    # ------------------------------------------------------------------
    @property
    def nu_anomaly_thz(self) -> float:
        """Первый дифракционный порядок решётки (аномалия Вуда), lambda = P."""
        return C_LIGHT_UM_THZ / self.P_um.value

    @property
    def zone_green_max_thz(self) -> float:
        return self.nu_anomaly_thz / 6.0

    @property
    def zone_red_min_thz(self) -> float:
        return self.nu_anomaly_thz / 1.5

    def zone(self, freqs_thz):
        nu = np.asarray(freqs_thz, dtype=float)
        out = np.full(nu.shape, "green", dtype=object)
        out[nu >= self.zone_green_max_thz] = "amber"
        out[nu >= self.zone_red_min_thz] = "red"
        return out

    def model_kwargs(self, *, d_eff=None, loss=None, gamma=None) -> dict:
        """Аргументы для blanco.dressed_t (с возможностью подмены для огибающих)."""
        return dict(
            p_um=self.P_um.value,
            d_um=self.D_eff_um.value if d_eff is None else d_eff,
            loss_factor=self.loss_factor.value if loss is None else loss,
            gamma=self.gamma.value if gamma is None else gamma,
            eta0=self.eta0.value, eta_exp=self.eta_exp, delta0=self.delta0,
            tau_leak_ps=self.tau_leak_ps.value,
            tau_par_ps=self.tau_par_ps.value,
            band=tuple(self.band_thz),
        )

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        def enc(o):
            if isinstance(o, Param):
                return {"value": o.value, "sigma": o.sigma, "source": o.source}
            if isinstance(o, (ScaleSpec, FilmPolarizer)):
                return asdict(o)
            return o
        d = {}
        for k, v in self.__dict__.items():
            d[k] = enc(v) if not isinstance(v, tuple) else list(v)
        return d

    def save(self, path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Passport":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        kw = {}
        for k, v in raw.items():
            if isinstance(v, dict) and "value" in v and "sigma" in v:
                kw[k] = Param(**v)
            elif k == "scale":
                kw[k] = ScaleSpec(**v)
            elif k == "film":
                kw[k] = FilmPolarizer(**v) if v else None
            elif k in ("band_thz", "gamma_range", "datasets"):
                kw[k] = tuple(v)
            else:
                kw[k] = v
        p = cls(**kw)
        p.validate()
        return p

    def validate(self) -> list[str]:
        """Проверка инвариантов. Возвращает список предупреждений, кидает на грубых ошибках."""
        warn = []
        if not (0 < self.band_thz[0] < self.band_thz[1]):
            raise ValueError(f"invalid calibration band {self.band_thz}")
        if not (0 < self.D_eff_um.value < self.P_um.value):
            raise ValueError("0 < D_eff < P is required")
        if self.D_eff_um.sigma == 0 and self.D_eff_um.source != "fixed":
            warn.append("D_eff without uncertainty - error estimates will be understated")
        if self.gamma.sigma == 0 and self.gamma_range[0] == self.gamma_range[1]:
            warn.append("gamma without a range - extrapolation envelope cannot be built")
        if self.scale.division_deg <= 0:
            raise ValueError("scale division must be > 0")
        return warn


# ---------------------------------------------------------------------------
def scale_for_aperture(aperture_mm: float) -> ScaleSpec:
    """Цена деления шкалы по апертуре прибора.

    Малые апертуры (<= 45 мм) — 2 град, большие — 1 град.
    Границу 45 мм задаёт технологическое деление Tydex: плёночные поляризаторы
    выпускаются по двум технологиям, D25-45 и D50-100.
    """
    return ScaleSpec(division_deg=2.0 if aperture_mm <= 45.0 else 1.0)


def film_for_aperture(aperture_mm: float) -> FilmPolarizer:
    """Спека плёночного поляризатора Tydex по апертуре (гарантированные значения).

    D25-45 : ER > 55000 (>47 дБ) @ 250-3000 мкм; > 350 (>25 дБ) @ 15-250 мкм
    D50-100: ER >  8500 (>39 дБ) @ 250-3000 мкм; > 250 (>24 дБ) @ 15-250 мкм
    """
    if aperture_mm <= 45.0:
        return FilmPolarizer(name="Tydex film D25-45", K1=0.80,
                             K2_low_band=0.80 / 55000, K2_high_band=0.80 / 350)
    return FilmPolarizer(name="Tydex film D50-100", K1=0.80,
                         K2_low_band=0.80 / 8500, K2_high_band=0.80 / 250)
