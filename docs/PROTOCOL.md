# Streamplify DECK USB protocol notes

Reverse-engineered on Linux. Observed on firmware `V2.One.00.001`.

## Device

| Field | Value |
|---|---|
| VID:PID | `0100:1000` |
| Strings | manufacturer `355`, product `35549` |
| Speed | USB 2.0 High Speed |
| Interface | 1× HID, vendor usage page `0xFFA0` |
| Endpoints | `0x82` interrupt IN, `0x01` interrupt OUT, 512 bytes each |
| Report IDs | none |

The descriptor layout and command set match the Mirabox/Ajazz "Stream Dock"
family, so the deck appears to be a rebadge of that chipset.

## Commands (host → device)

Every OUT report is 512 bytes, zero-padded. Commands start with `CRT\0\0`.

| Command | Bytes after `CRT\0\0` | Effect |
|---|---|---|
| Wake display | `DIS` | Turn the screen on |
| Brightness | `LIG\0\0<pct>` | 0–100 |
| Clear | `CLE\0\0\0<key>` | `0xFF` = all keys |
| Refresh | `STP` | Commit uploaded images to the screen |
| Key image | `BAT<len:u32 BE><key>` | Followed by `len` bytes of JPEG in raw 512-byte packets |

Key images are **100×100 JPEG, rotated 180°** before encoding.

Firmware version: `GET_FEATURE_REPORT` with report ID 0 returns an ASCII string.

Not touched on purpose: boot-logo and firmware commands (these write to flash).

## Input (device → host)

IN reports start with `ACK\0\0OK\0\0`; byte 9 is the key number, byte 10 the
state (`1` = pressed, `0` = released).

## Key numbering

Image indices and input indices **differ**:

```
physical layout     image index        input index
(top → bottom)
 row 0              11 12 13 14 15     1  2  3  4  5
 row 1               6  7  8  9 10     6  7  8  9 10
 row 2               1  2  3  4  5    11 12 13 14 15
```

The driver translates input indices to image indices, so the API only ever
uses image indices.

## Throughput (measured)

| Operation | Cost |
|---|---|
| Raw 512-byte packet | ~0.6 ms |
| Image upload (device-side processing) | ~20 ms, almost independent of size |
| `STP` refresh | ~40 ms |
| One key, upload + refresh | ~14–16 fps |
| All 15 keys + one refresh | ~1.5–2 fps |

So the budget is roughly 45 key images per second. Batch uploads and send one
`STP` per frame.

## Pitfall: never interrupt an image upload

If the host stops partway through a `BAT` upload (process killed, exception),
the deck keeps waiting for the rest of the JPEG and treats the next commands as
image data. Its firmware then gets confused: the screen still accepts images,
but the IN endpoint floods oversized packets, the kernel logs
`usb 1-1: input irq status -75` (EOVERFLOW) hundreds of times per second, and
**no button presses arrive**.

- The client avoids this by handling SIGTERM/SIGINT with a flag that is only
  checked between operations, so a stop always finishes the current upload.
- The client USB-resets the deck whenever it starts (and after losing it), so a
  deck left in this state by a crash, `kill -9` or power loss heals itself.
  Manual recovery: `streamplify reset`, `sudo usbreset 0100:1000`, or replug.
