"""Модель аттенюатора: ДВА поляризатора в ротаторах, произвольное состояние
источника, произвольный тип приёмника, азимут поляризации на выходе.

Зачем нужна отдельно от `service_calc.transmission_array`
--------------------------------------------------------
Формула C9 (`service_calc`, 18.08) считает ОДИН угол при трёх неявных допущениях:
WGP2 закреплён по оси детектора, источник линейный и полностью поляризован,
приёмник когерентный. Владелец (2026-08-24): «оба в ротаторах, но крутят руками
по обстановке» -- значит допущения неверны уже сейчас. Здесь они сняты, но
ФИЗИКА НЕ МЕНЯЕТСЯ: при подстановке прежних допущений формула сводится к
`service_calc` тождественно (проверка T1, допуск 1e-12).

Почему матрица когерентности, а не матрицы Мюллера
--------------------------------------------------
Состояние света переносится на матрицу когерентности ``J = <E E^H>`` (2x2
эрмитова). Она эквивалентна вектору Стокса (биекция через матрицы Паули), но
распространяется ЧЕРЕЗ ТЕ ЖЕ матрицы Джонса: ``J_out = M J_in M^H``. Это важно
не из вкуса: поэлементная интенсивностная (некогерентная) запись теряет фазу
утечки, потому что фаза входит только через 4-ю гармонику. Цена измерена в
проекте дважды -- смещение углового офсета до -12.6 град и экстинкция 17.06 дБ
вместо 28.20 (`track_viewer/core/fit_malus.py`, `docs/track_viewer/01_FORMATS.md`
§6.3). Матрица когерентности этот риск снимает структурно и при этом даёт
частичную поляризацию точно, а не двумя крайними значениями DOP.

Схема и конвенция углов
-----------------------
    источник(psi, DOP) -> WGP1(theta1) -> WGP2(theta2) -> приёмник(A)

    J_out = M J_in M^H,     M = J2(theta2 - off2) . J1(theta1 - off1)
    I     = Tr(A J_out)

Углы -- ориентация ОСИ ПРОПУСКАНИЯ элемента (перпендикулярно проводам), градусы,
против часовой стрелки; провода лежат под angle+90. Та же конвенция, что в
`attenuator_app/core/forward.py` и `research/two_wgp/model_2wgp.py`; отступление
от неё -- источник ошибки на 90 град.

Оба WGP считаются ИДЕНТИЧНЫМИ (общие t_perp, t_par из `core.blanco.dressed_t`),
как и в C9. Независимую геометрию на элемент здесь НЕ вводим сознательно:
параметры модели уже вырождены (`D_eff <-> eta` корреляция +-1.0,
`research/SYNTHESIS.md`), и вдвое разный `P` укладывается внутрь паспортной RMSE.

Приёмник -- одна формула на все типы
------------------------------------
``I = Tr(A J_out)``, где A -- эрмитова матрица чувствительности:

    когерентный (PCA, электрооптика)  A = d d^H     -- проекция ПОЛЯ на ось d
    мощностной (болометр, Голей)      A = 1         -- оси анализатора нет физически

Вторая роль WGP2: азимут на выходе
----------------------------------
В идеальном пределе поляризация на выходе аттенюатора лежит по оси WGP2
(``chi == theta2``); утечка ``t_par`` слегка уводит азимут, и матрица
когерентности даёт этот увод точно, в том числе для частично поляризованного
входа. Это существенно в установках с МОЩНОСТНЫМ приёмником: анализатора там
нет, приёмнику азимут безразличен, но образцу и оптике ниже по тракту -- нет.

⚠ ГРАНИЦА ЭТОГО УТВЕРЖДЕНИЯ. «Азимут задаёт WGP2» верно в рабочей области, но
отказывает у скрещенного положения. Две ОДИНАКОВЫЕ решётки в скрещении
поляризационно НЕЙТРАЛЬНЫ: первая давит x как |t_perp|^2 и y как |t_par|^2,
вторая наоборот, произведение изотропно, и на выходе воспроизводится ВХОДНОЕ
состояние (проверка T7). Поэтому у самого дна азимут возвращается к оси
источника, а не к оси WGP2. Измерено на канонической калибровке при 0.8 ТГц:

    theta2      30      60      80      85      88      89     89.5     90
    ослабл.,дБ  1.2     6.0    15.2    21.1    28.6    33.3    36.2    37.8
    chi-theta2 -0.01   -0.02   -0.06   -0.12   -0.35   -1.33  -88.97  -90.00

То есть до ~28 дБ азимутом можно управлять с точностью лучше 0.4 град, а в
последнем градусе перед скрещением управление теряется полностью. Прямое
следствие для обратной задачи по двум углам: пара «очень глубокое ослабление +
заданный азимут» недостижима, и отказ должен называть именно эту причину.

Запуск самопроверки из корня репозитория:
    python -m attenuator_app.tools.service_model --selftest
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from attenuator_app.core.blanco import dressed_t          # noqa: E402

#: типы приёмника -- см. докстринг модуля
DETECTORS = {
    "coherent": "когерентный (PCA, электрооптика): проекция ПОЛЯ на ось анализатора",
    "power": "мощностной (болометр, пироприёмник, Голей): полная мощность, оси нет",
}
#: типы источника
SOURCES = {
    "linear": "линейно поляризованный, азимут psi (DOP = 1)",
    "unpolarized": "неполяризованный / деполяризованный (DOP = 0)",
    "partial": "частично поляризованный: азимут psi и произвольный DOP",
}


# --- состояние поляризации --------------------------------------------
@dataclass(frozen=True)
class PolState:
    """Состояние поляризации в параметрах Стокса.

    Имена компонент -- ``I, Q, U, V``, а НЕ ``S0..S3``: в этом репозитории
    ``S0/S1/S2/S3`` заняты сразу на трёх уровнях -- имена оптических схем
    (`core/forward.SCHEMES`, `passport.fit_scheme`), серии измерений
    (`att-11-16-s2`) и локальные переменные внутри
    `core/forward.output_polarization`. Совпадение имён здесь стоило бы дороже
    краткости.

    Конвенция знака ``V`` -- как в `core/forward.output_polarization`:
    ``V = -2 Im<Ex conj(Ey)>``.
    """

    I: float = 1.0
    Q: float = 0.0
    U: float = 0.0
    V: float = 0.0

    def __post_init__(self):
        if self.I <= 0:
            raise ValueError("полная интенсивность I должна быть положительной")
        p = np.hypot(np.hypot(self.Q, self.U), self.V)
        if p > self.I * (1.0 + 1e-12):
            raise ValueError(
                f"нефизичное состояние: sqrt(Q^2+U^2+V^2) = {p:.6g} > I = {self.I:.6g}")

    # -- конструкторы под три типа источника из SOURCES
    @classmethod
    def linear(cls, psi_deg: float = 0.0) -> "PolState":
        t = 2.0 * np.deg2rad(psi_deg)
        return cls(1.0, float(np.cos(t)), float(np.sin(t)), 0.0)

    @classmethod
    def unpolarized(cls) -> "PolState":
        return cls(1.0, 0.0, 0.0, 0.0)

    @classmethod
    def partial(cls, dop: float, psi_deg: float = 0.0) -> "PolState":
        if not 0.0 <= dop <= 1.0:
            raise ValueError("DOP должен лежать в [0, 1]")
        t = 2.0 * np.deg2rad(psi_deg)
        return cls(1.0, float(dop * np.cos(t)), float(dop * np.sin(t)), 0.0)

    @classmethod
    def from_source(cls, kind: str, psi_deg: float = 0.0,
                    dop: float = 1.0) -> "PolState":
        """Состояние по имени типа источника из `SOURCES`."""
        if kind == "linear":
            return cls.linear(psi_deg)
        if kind == "unpolarized":
            return cls.unpolarized()
        if kind == "partial":
            return cls.partial(dop, psi_deg)
        raise ValueError(f"неизвестный тип источника {kind!r}, ожидается один из {list(SOURCES)}")

    @property
    def dop(self) -> float:
        """Степень поляризации."""
        return float(np.hypot(np.hypot(self.Q, self.U), self.V) / self.I)

    def coherency(self) -> np.ndarray:
        """Матрица когерентности 2x2: J = 1/2 [[I+Q, U-iV], [U+iV, I-Q]]."""
        return 0.5 * np.array([[self.I + self.Q, self.U - 1j * self.V],
                               [self.U + 1j * self.V, self.I - self.Q]], dtype=complex)


def stokes_from_coherency(J: np.ndarray) -> tuple:
    """(I, Q, U, V) из матрицы когерентности произвольной формы (..., 2, 2)."""
    Jxx, Jxy = J[..., 0, 0], J[..., 0, 1]
    Jyy = J[..., 1, 1]
    I = np.real(Jxx + Jyy)
    Q = np.real(Jxx - Jyy)
    U = 2.0 * np.real(Jxy)
    V = -2.0 * np.imag(Jxy)
    return I, Q, U, V


def polarization_of(J: np.ndarray) -> dict:
    """Азимут (град), эллиптичность (град) и DOP по матрице когерентности.

    Азимут ``chi = 1/2 atan2(U, Q)`` -- плоскость поляризации на выходе
    аттенюатора; в идеальном пределе она совпадает с осью WGP2.
    """
    I, Q, U, V = stokes_from_coherency(J)
    p = np.sqrt(Q ** 2 + U ** 2 + V ** 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        chi = 0.5 * np.degrees(np.arctan2(U, Q))
        ellip = 0.5 * np.degrees(np.arcsin(np.clip(V / np.maximum(p, 1e-300), -1.0, 1.0)))
        dop = p / np.maximum(I, 1e-300)
    return {"azimuth_deg": chi, "ellipticity_deg": ellip, "dop": dop, "intensity": I}


# --- приёмник ----------------------------------------------------------
@dataclass(frozen=True)
class Analyzer:
    """Матрица чувствительности приёмника: ``I = Tr(A J_out)``.

    `kind='coherent'` -- проекция поля на ось `axis_deg`, ``A = d d^H``.
    `kind='power'`    -- полная мощность обеих компонент, ``A = 1``; ось
    анализатора игнорируется, потому что у мощностного приёмника её физически
    нет (болометр, пироприёмник, ячейка Голея).
    """

    kind: str = "coherent"
    axis_deg: float = 0.0

    def __post_init__(self):
        if self.kind not in DETECTORS:
            raise ValueError(
                f"неизвестный приёмник {self.kind!r}, ожидается один из {list(DETECTORS)}")

    @property
    def uses_axis(self) -> bool:
        """Влияет ли ось анализатора на показание (для подсказок в интерфейсе)."""
        return self.kind == "coherent"

    def matrix(self) -> np.ndarray:
        if self.kind == "power":
            return np.eye(2, dtype=complex)
        t = np.deg2rad(float(self.axis_deg))
        d = np.array([np.cos(t), np.sin(t)], dtype=complex)
        return np.outer(d, d.conj())


# --- цепочка Джонса ----------------------------------------------------
def _jones(phi_deg, a, b) -> np.ndarray:
    """Матрица Джонса элемента: ось пропускания phi, амплитуды (a, b).

    Совпадает с `core/forward._jones`; продублирована здесь, чтобы рантайм
    сервисного приложения не зависел от клиентского ядра (тот же принцип
    изоляции, что у `service_calc`).

    phi_deg : скаляр или (n_ang,);  a, b : (n_f,)  ->  (n_ang, n_f, 2, 2)
    """
    phi = np.deg2rad(np.atleast_1d(np.asarray(phi_deg, dtype=float))[:, None])
    a = np.asarray(a, dtype=complex)[None, :]
    b = np.asarray(b, dtype=complex)[None, :]
    c, s = np.cos(phi), np.sin(phi)
    cc, ss, cs = c * c, s * s, c * s
    j00, j11, j01 = np.broadcast_arrays(a * cc + b * ss, a * ss + b * cc, (a - b) * cs)
    return np.stack([np.stack([j00, j01], -1), np.stack([j01, j11], -1)], -2)


def chain(theta1_deg, theta2_deg, freqs_thz, P_um: float = 0.0, D_um: float = 0.0, *,
          loss_factor: float = 0.0, gamma: float = 2.0,
          off1_deg: float = 0.0, off2_deg: float = 0.0,
          ideal: bool = False) -> np.ndarray:
    """Полная матрица Джонса пары WGP: (n_ang, n_f, 2, 2).

    `theta1_deg`, `theta2_deg` -- показания шкал обоих ротаторов (широковещаются
    друг к другу); `off1_deg`, `off2_deg` -- механические офсеты своих шкал.

    `ideal=True` -- идеализация элементов ``t_perp = 1, t_par = 0``; геометрия
    при этом не используется. Нужна для эталонных законов (`cos^4`, `cos^2`) и
    приёмочных проверок. Задавать идеал вырожденной геометрией НЕЛЬЗЯ: у модели
    Бланко тонкая проволока почти прозрачна для ОБЕИХ поляризаций, максимум
    экстинкции лежит при промежуточном `D/P` (см. `core/passport.py`).
    """
    nu = np.ascontiguousarray(freqs_thz, dtype=float)
    if ideal:
        tp = np.ones(nu.shape, dtype=complex)
        ta = np.zeros(nu.shape, dtype=complex)
    else:
        tp, ta, _clipped = dressed_t(nu, P_um, D_um, loss_factor=loss_factor, gamma=gamma)

    th1 = np.atleast_1d(np.asarray(theta1_deg, dtype=float)) - off1_deg
    th2 = np.atleast_1d(np.asarray(theta2_deg, dtype=float)) - off2_deg
    th1, th2 = np.broadcast_arrays(th1, th2)

    return np.einsum("...ij,...jk->...ik", _jones(th2, tp, ta), _jones(th1, tp, ta))


def propagate(M: np.ndarray, state: PolState) -> np.ndarray:
    """J_out = M J_in M^H, форма (n_ang, n_f, 2, 2)."""
    return np.einsum("...ij,jk,...lk->...il", M, state.coherency(), M.conj())


def detected(J_out: np.ndarray, analyzer: Analyzer) -> np.ndarray:
    """Показание приёмника I = Tr(A J_out), форма (n_ang, n_f), вещественное."""
    return np.real(np.einsum("mn,...nm->...", analyzer.matrix(), J_out))


def response(theta1_deg, theta2_deg, freqs_thz, P_um: float = 0.0, D_um: float = 0.0, *,
             loss_factor: float = 0.0, gamma: float = 2.0,
             off1_deg: float = 0.0, off2_deg: float = 0.0,
             ideal: bool = False,
             source: PolState | None = None,
             analyzer: Analyzer | None = None) -> dict:
    """Полный отклик схемы: показание приёмника и поляризация на выходе.

    Возвращает словарь, все массивы формы (n_ang, n_f):

        intensity        показание приёмника, Tr(A J_out)
        intensity_total  полная мощность обеих компонент, Tr(J_out)
        azimuth_deg      азимут поляризации ПОСЛЕ аттенюатора (задаёт WGP2)
        ellipticity_deg  эллиптичность там же
        dop              степень поляризации там же

    Азимут возвращается всегда, в том числе при мощностном приёмнике: приёмнику
    он безразличен, а образцу и оптике ниже по тракту -- нет.
    """
    src = PolState.linear(0.0) if source is None else source
    ana = Analyzer() if analyzer is None else analyzer
    M = chain(theta1_deg, theta2_deg, freqs_thz, P_um, D_um,
              loss_factor=loss_factor, gamma=gamma,
              off1_deg=off1_deg, off2_deg=off2_deg, ideal=ideal)
    J_out = propagate(M, src)
    out = polarization_of(J_out)
    out["intensity_total"] = out.pop("intensity")
    out["intensity"] = detected(J_out, ana)
    return out


# --- самопроверка ------------------------------------------------------
def _check(results, name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'OK' if ok else '!!'}] {name}   {detail}")


def selfcheck() -> int:
    """Численные инварианты модели. Без файлов и графиков."""
    print("\n=== attenuator_app.tools.service_model: самопроверка ===\n")
    res = []
    P, D, loss, gam = 32.94766016244776, 9.920978256304087, 0.26069787616947165, 0.5691763812786808
    nu = np.array([0.8])
    th = np.array([0.0, 20.0, 45.0, 70.0, 85.0])

    # T1. Сведение к формуле C9: WGP2 стоит в своём нуле, источник линейный
    #     вдоль x, приёмник когерентный с осью x. Это ровно те допущения,
    #     на которых написан `service_calc.transmission_array`.
    tp, ta, _ = dressed_t(nu, P, D, loss_factor=loss, gamma=gam)
    d = np.deg2rad(th)
    e1 = tp[None, :] * np.cos(d)[:, None] ** 2 + ta[None, :] * np.sin(d)[:, None] ** 2
    ref_c9 = np.abs(tp[None, :]) ** 2 * np.abs(e1) ** 2          # 'p0' из service_calc
    got = response(th, 0.0, nu, P, D, loss_factor=loss, gamma=gam,
                   source=PolState.linear(0.0),
                   analyzer=Analyzer("coherent", 0.0))["intensity"]
    err = float(np.max(np.abs(got - ref_c9)))
    _check(res, "T1  сведение к формуле C9 (два WGP -> один угол)",
           err < 1e-12, f"макс |dI| = {err:.2e}")

    # T2. Идеальный предел: cos^4 у когерентного, cos^2 у мощностного.
    #     Вращаем WGP2 при закреплённом WGP1 -- конвенция паспорта.
    def law(analyzer, src, n_expect):
        r = response(0.0, th, nu, ideal=True, source=src, analyzer=analyzer
                     )["intensity"][:, 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            n = -10.0 * np.log10(r[1:] / r[0]) / (-10.0 * np.log10(np.cos(np.deg2rad(th[1:]))))
        return float(np.max(np.abs(n - n_expect)))

    e_coh = law(Analyzer("coherent", 0.0), PolState.linear(0.0), 4.0)
    e_pow = law(Analyzer("power"), PolState.linear(0.0), 2.0)
    _check(res, "T2  идеальный предел: когерентный cos^4, мощностной cos^2",
           e_coh < 1e-9 and e_pow < 1e-9, f"|dn| = {e_coh:.2e} / {e_pow:.2e}")

    # T3. Первый WGP стирает поляризацию источника: у деполяризованного ФОРМА
    #     кривой та же, что у линейного, а абсолютный сдвиг ровно 10*log10(2).
    #     Точное равенство формы -- свойство ИДЕАЛЬНОГО элемента; у реальной
    #     решётки остаётся член порядка утечки, потому что WGP1 стирает не
    #     нацело (после него у неполяризованного входа выживает |t_par|^2).
    def shape_shift(**kw):
        a = response(0.0, th, nu, source=PolState.linear(0.0),
                     analyzer=Analyzer("power"), **kw)["intensity"][:, 0]
        b = response(0.0, th, nu, source=PolState.unpolarized(),
                     analyzer=Analyzer("power"), **kw)["intensity"][:, 0]
        return float(np.max(np.abs(a / a[0] - b / b[0]))), float(10.0 * np.log10(a[0] / b[0]))

    s_id, sh_id = shape_shift(ideal=True)
    s_re, sh_re = shape_shift(P_um=P, D_um=D, loss_factor=loss, gamma=gam)
    tp0, ta0, _ = dressed_t(nu, P, D, loss_factor=loss, gamma=gam)
    eta2 = float(np.abs(ta0[0] / tp0[0]) ** 2)          # утечка по мощности
    # У реальной решётки в совмещённом положении линейный вход даёт |t_perp|^4,
    # а неполяризованный -- (|t_perp|^4 + |t_par|^4)/2, поэтому точный сдвиг есть
    # 10*log10(2/(1+eta^4)), а не ровно 10*log10(2). Поправка второго порядка по
    # утечке; отклонение формы -- первого порядка и потому заметно больше.
    sh_exact = float(10.0 * np.log10(2.0 / (1.0 + eta2 ** 2)))
    _check(res, "T3  WGP1 стирает поляризацию: форма та же, сдвиг 10log10(2)",
           s_id < 1e-12 and abs(sh_id - 3.010299956639812) < 1e-12
           and s_re < 2.0 * eta2 and abs(sh_re - sh_exact) < 1e-9,
           f"идеал {s_id:.1e}/{sh_id:.6f} дБ; реальная форма {s_re:.2e} "
           f"при утечке {eta2:.2e}, сдвиг {sh_re:.9f} против точного {sh_exact:.9f}")

    # T4. Какой поляризатор вращаем: для мощностного приёмника это меняет закон,
    #     для когерентного с анализатором по WGP2 -- нет.
    def n_of(r):
        c = np.cos(np.deg2rad(th[1:]))
        return float(np.max(np.abs(-10 * np.log10(r[1:] / r[0]) / (-10 * np.log10(c)))))

    pw = Analyzer("power")
    rot2 = response(0.0, th, nu, ideal=True, source=PolState.linear(0.0), analyzer=pw)
    rot1 = response(th, 0.0, nu, ideal=True, source=PolState.linear(0.0), analyzer=pw)
    n2, n1 = n_of(rot2["intensity"][:, 0]), n_of(rot1["intensity"][:, 0])
    _check(res, "T4  мощностной: вращаем WGP2 -> cos^2, WGP1 -> cos^4",
           abs(n2 - 2.0) < 1e-9 and abs(n1 - 4.0) < 1e-9, f"n = {n2:.6f} / {n1:.6f}")

    # T5. Азимут на выходе задаёт WGP2: в идеальном пределе chi == theta2.
    ang = np.array([-60.0, -20.0, 0.0, 35.0, 80.0])

    def azim_dev(**kw):
        chi = response(0.0, ang, nu, source=PolState.linear(0.0),
                       analyzer=Analyzer("power"), **kw)["azimuth_deg"][:, 0]
        return float(np.max(np.abs((chi - ang + 90.0) % 180.0 - 90.0)))

    d_id = azim_dev(ideal=True)
    d_re = azim_dev(P_um=P, D_um=D, loss_factor=loss, gamma=gam)
    _check(res, "T5  азимут выхода = ось WGP2 (идеал), увод с утечкой мал",
           d_id < 1e-9 and d_re < 1.0,
           f"идеал {d_id:.1e} град, реальная решётка {d_re:.4f} град")

    # T6. Энергия не растёт, период 180 град, поляризатор не уменьшает DOP.
    wide = np.linspace(-180.0, 180.0, 145)
    r_un = response(0.0, wide, nu, P, D, loss_factor=loss, gamma=gam,
                    source=PolState.unpolarized(), analyzer=Analyzer("power"))
    i_un = r_un["intensity"][:, 0]
    src_part = PolState.partial(0.30, 20.0)
    r_pt = response(0.0, wide, nu, P, D, loss_factor=loss, gamma=gam,
                    source=src_part, analyzer=Analyzer("power"))
    grew = float(np.max(i_un))
    per = float(np.max(np.abs(i_un[:73] - i_un[72:])))
    d_gain = float(np.min(r_pt["dop"]) - src_part.dop)
    _check(res, "T6  энергия <= 1, период 180 град, DOP не убывает после WGP",
           grew <= 1.0 + 1e-12 and per < 1e-12 and d_gain >= -1e-12,
           f"max I = {grew:.6f}, период {per:.1e}, "
           f"DOP {src_part.dop:.3f} -> min {np.min(r_pt['dop']):.4f}")

    # T7. Скрещенная пара ОДИНАКОВЫХ WGP поляризационно нейтральна: первая
    #     давит x как |t_perp|^2 и y как |t_par|^2, вторая наоборот, произведение
    #     изотропно => J_out = |t_perp|^2 |t_par|^2 * J_in для ЛЮБОГО входа.
    #     Отсюда у дна азимут возвращается к оси источника, а не WGP2.
    src7 = PolState.partial(0.55, 37.0)
    M7 = chain(0.0, 90.0, nu, P, D, loss_factor=loss, gamma=gam)
    J7 = propagate(M7, src7)[0, 0]
    scale = float(np.real(np.trace(J7)) / src7.I)
    resid = float(np.max(np.abs(J7 / scale - src7.coherency())))
    p7 = polarization_of(J7)
    d_az = float((p7["azimuth_deg"] - 37.0 + 90.0) % 180.0 - 90.0)
    _check(res, "T7  скрещенная пара одинаковых WGP поляризационно нейтральна",
           resid < 1e-12 and abs(p7["dop"] - src7.dop) < 1e-12 and abs(d_az) < 1e-9,
           f"|J_out/k - J_in| = {resid:.1e}, DOP {src7.dop:.3f} -> {p7['dop']:.3f}, "
           f"азимут -> ось источника ({d_az:+.1e} град)")

    bad = [n for n, ok, _ in res if not ok]
    print(f"\n=== {len(res) - len(bad)}/{len(res)} пройдено ===")
    if bad:
        print("НЕ ПРОШЛИ: " + ", ".join(bad))
    return 1 if bad else 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selfcheck()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
