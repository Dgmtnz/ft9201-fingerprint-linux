# Driver FocalTech FT9201 (2808:9338) para Linux

Soporte funcional del lector de huella **FocalTech FT9201** en Linux, con
integración completa en KDE Plasma vía `fprintd` y PAM.

Probado en Alurin ALU-BAR-R75825-000-156 (Ryzen 7 5825U), CachyOS, kernel 7.1.4.

## Estado

| | |
|---|---|
| Protocolo USB / captura | funciona (viene de la MR !572 de libfprint) |
| Matcher | funciona tras recalibrar tres parámetros |
| Aceptación del dedo legítimo | 8/8 en vivo (scores 0,874–0,951) |
| Rechazo de dedos ajenos | 10/10 en vivo (scores 0,111–0,446) |
| EER medido | ~0,07% |
| KDE (desbloqueo + polkit) | integrado |

## De dónde sale

La base es la [MR !572 de libfprint](https://gitlab.freedesktop.org/libfprint/libfprint/-/merge_requests/572)
de 0xCoDSnet, que resolvió la ingeniería inversa del protocolo USB. Está abierta
sin mergear. Este repo aporta la calibración del matcher, que es lo que impedía
que el driver verificara de forma fiable.

**Importante:** los drivers de lectores USB de huella no van al kernel. Van a
libfprint, en espacio de usuario sobre libusb.

## Estado de la contribución upstream

**MR abierta: [libfprint!646](https://gitlab.freedesktop.org/libfprint/libfprint/-/merge_requests/646)**
— 10 commits, los 6 originales de @0xCoDSnet con su autoría intacta más los 4 de este
trabajo. Continúa la [!572](https://gitlab.freedesktop.org/libfprint/libfprint/-/merge_requests/572),
sin tocar desde marzo de 2026, y aplica de paso las sugerencias de revisión pendientes.

## Los tres parámetros

```
FT9201_SEARCH_RADIUS       3 -> 16     el desplazamiento real entre pulsaciones
FT9201_NUM_ENROLL_STAGES   5 -> 15     cada plantilla cubre poca área del dedo
FT9201_NCC_THRESHOLD    0.30 -> 0.55   con margen deliberado sobre el óptimo
```

Medidos sobre 25 capturas genuinas y 24 de impostores, no estimados. Detalle y
metodología en [`upstream/INFORME-MR572.md`](upstream/INFORME-MR572.md).

## Aviso sobre datasets

Si recoges capturas para evaluar, **pon el dedo como en el uso real, siempre
igual**. No "variando la posición": el sensor mide 3x4 mm y variar la postura
captura zonas disjuntas del dedo, que no correlacionan entre sí. Con un dataset
así, todo matcher da EER ~45% y parece que nada funciona. Con capturas naturales,
el mismo matcher da 0,07%.

## Contenido

```
upstream/        4 parches + informe para la MR !572
paquete/         PKGBUILD de libfprint-tod-ft9201 para Arch
analyze_*.py     evaluación de matchers (el válido es analyze_decision.py)
matcher_*.py     desarrollo del matcher, incluido BLPOC
fp-test.sh       enroll/verify contra el build local sin instalar nada
```

El dataset de calibración (74 capturas) **no se publica**: son huellas dactilares
reales y, a diferencia de una contraseña, no se pueden cambiar si se filtran.
Quien quiera reproducir las medidas debe recoger las suyas con `fp-collect`.

## Compilar y probar sin tocar el sistema

Este repo no incluye el árbol de libfprint. Se reconstruye así:

```sh
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cd libfprint
git fetch origin refs/merge-requests/572/head:mr572
git checkout mr572
git am ../upstream/*.patch

meson setup build -Ddrivers=focaltech_moh -Dintrospection=false -Ddoc=false \
                  -Dgtk-examples=false -Dinstalled-tests=false
ninja -C build
cd .. && ./fp-test.sh enroll   # y luego ./fp-test.sh verify
```

## Instalar en Arch

```sh
cd paquete && makepkg -f && sudo pacman -U libfprint-tod-ft9201-*.pkg.tar.zst
```

Sustituye a `libfprint-tod`. Es necesario ir por el fork TOD porque el `fprintd`
de Arch enlaza contra `libfprint-2.so.2` **y** `libfprint-2-tod.so.1`.

## Descartado con datos

**NBIS / bozorth3** (la vía `FpImageDevice`) no sirve aquí: el sensor da 2–4
minucias por imagen y bozorth3 necesita ~12. Comprobado con `ppmm` de 8 a 40 y
ambas polaridades de cresta. `libfprint/libfprint/nbis-bench.c` reproduce la
medición.

**BLPOC** (correlación de fase de banda limitada) funciona correctamente
—verificado con pruebas de sanidad— pero rinde peor que la NCC en este sensor.

## Licencia

LGPL-2.1-or-later, como libfprint. El driver es obra original de 0xCoDSnet.
