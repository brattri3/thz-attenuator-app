# THz Attenuator App

*[Русская версия](README.ru.md)*

Control and calibration software for terahertz attenuators built on wire-grid polarisers (WGP) —
the **ATT-11-16-CA85** family. It answers one question at the instrument: **what transmission does
a given pair of rotator angles give at a chosen frequency**, and the other way round — what angle
produces the attenuation you need.

The physics is the **Blanco (1986)** model in the Jones-matrix formalism, extended with Drude
conductivity and a power-law scattering term. The state of light is carried by the coherency
matrix `J = ⟨E E†⟩`, so a coherent receiver and a power receiver are described by the same model
without losing the phase of the parallel leakage channel.

## Download

Ready-to-run build for Windows x64 — no Python needed:

**[Releases](https://github.com/brattri3/thz-attenuator-app/releases/latest)** · archive
`THz-Attenuator-<version>-win64.zip` (about 57 MB, about 144 MB unpacked) with a `.sha256`
checksum file beside it.

Unpack anywhere and run `THz-Attenuator.exe`. Verify the archive first:

```
certutil -hashfile THz-Attenuator-0.1.0-win64.zip SHA256
```

Qt libraries ship as separate files next to the executable rather than bundled inside it, so they
can be replaced with your own Qt build — see [Licence](#licence).

## Device passport — read this before measuring

The parameters of **your** instrument live in a separate passport file delivered with the device.
It is not in this repository and never will be: a public repository is no place for the data of an
individual unit.

**File naming — one rule:**

```
<model>-<serial number>.json        for example  ATT-11-16-CA85-02721.json
```

The file name must match the `device_id` inside the file, character for character. One instrument —
one file. **Do not put the calibration date in the name:** the application scans the folder in
sorted order and takes the first valid file, so two dated passports of the same unit would
silently select the older calibration.

**Where the application looks**, in order:

1. the file you pick explicitly with the **Passport…** button;
2. next to the program — the `passports/` subfolder first, then the folder holding the executable;
3. the built-in anonymised sample, as a last resort.

Whatever it ends up using is named in the status bar. If it falls back to the sample, the status
bar says `built-in SAMPLE — not your device`: the sample is physically meaningful but **must not
be used for measurements**. If a file name disagrees with the `device_id` inside it, the
application keeps counting by `device_id` and says so in the status bar.

## Reading the numbers

* **0 dB is the maximum transmission** reachable by rotating the gratings, not the reading at zero
  on both scales. With an untilted source the two coincide. With a tilted source the maximum moves
  away from zero, the window names its new position, and readings **cannot be compared** with runs
  taken at a different source azimuth — the window warns about this.
* Frequencies outside the calibrated band are still computed, but flagged as extrapolation rather
  than measurement.
* Every reading carries the cost of a 1° setting error on each rotator, and the combined estimate.

## Instrument behaviour that is not a fault

* A crossed pair of **identical** WGPs is polarisation-neutral: at the bottom of the range the
  output reproduces the state of the source, not the axis of the second grating. The azimuth holds
  to better than 0.4° down to about 28 dB and is lost entirely in the last degree before crossing.
* For a coherent receiver, rotating the second grating puts the maximum **halfway** between the
  axis of the first grating and the analyser axis, not at alignment. A naive `argmax` therefore
  yields a shifted calibration zero.
* With a power receiver, rotating the second grating gives `cos²` while rotating the first gives
  `cos⁴` — twice as deep in decibels. Which grating sits in the rotator matters during calibration.

## Updates

The **Check for updates** button reads the published release list and reports one of four answers:
you are up to date, a newer version exists, there are no releases yet, or the check could not be
completed. A machine with no internet access is normal at a spectrometer, so a failed check is an
ordinary answer rather than a malfunction.

**The application never updates itself.** Downloading and installing is done by hand, deliberately:
instrument software must not change between two measurements of one series.

## Running from source

```
pip install -r requirements.txt
pip install PySide6-Essentials==6.11.2 pyqtgraph==0.14.0
python -m attenuator_app.cwapp
```

Qt is installed by a separate command on purpose: the full `PySide6` package pulls in QtWebEngine,
Qt3D and Charts — hundreds of megabytes, none of which this application needs.

Service tools for bench work — a two-rotator calculator, the P0…P4 calibration procedures and a
tkinter service window — are described in `docs/attenuator_app/`.

## Licence

The application is licensed under the **Apache License 2.0** — see `LICENSE` and `NOTICE`.

It uses **Qt through PySide6 under the LGPL-3.0**. That is why the build ships as a folder with Qt
libraries as separate files rather than as a single executable: the licence requires that the
recipient be able to replace Qt with their own build, and this form of delivery makes that
possible. Full licence texts of all components travel with the release in `LICENSES.txt`.
