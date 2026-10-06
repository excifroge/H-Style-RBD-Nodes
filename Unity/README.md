# Unity files for H-Style RBD Nodes

These four files play a VAT export from the extension in Unity (URP). They are not part of the Blender extension; download them here, or as `h_style_rbd_unity-x.y.z.zip` from the [Releases](https://github.com/excifroge/H-Style-RBD-Nodes/releases) page.

| File | What it is |
|---|---|
| `HStyleRbdVAT_URP.shader` | A URP shader that works as it is, with shadow and depth passes. Lighting is the main directional light plus ambient |
| `HStyleRbdVAT.hlsl` | The decode function, for calling from your own shader. How to use it is written at the top of the file |
| `HStyleRbdVatSetup.cs` | Editor menu **Assets > H-Style RBD Nodes > Set Up VAT From Json** |
| `HStyleRbdVatPlayer.cs` | Playback component: plays the clip once, and can emit particles where the pieces break apart |

## Use

1. Copy the four files anywhere under `Assets`. Keep one copy per project.
2. Put an export (`.json`, two `.exr`, `_mesh.fbx`) in a folder under `Assets`.
3. Select the `.json` and run **Assets > H-Style RBD Nodes > Set Up VAT From Json**. It fixes the texture import settings and creates a material and a prefab.

Checked with Unity 6 (6000.0 LTS) and Universal Render Pipeline 17. The [README](../README.md#export) has the details.

## License

CC0-1.0. Copy them into any project, commercial games included.
