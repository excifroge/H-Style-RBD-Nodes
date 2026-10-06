# Listing on extensions.blender.org

The text and pictures of the extension's page on the Blender Extensions platform. The pictures are rendered
from the example files by `Tools/listing_images.py`.

- **Support**: https://github.com/excifroge/H-Style-RBD-Nodes/issues
- **Featured image**: `featured.png` (1920 x 1080)
- **Icon**: `icon.png` (256 x 256)
- **Previews**: `preview_wall.png`, `preview_explosion.png`, `preview_ground.png`, `preview_glass.png`,
  `Docs/Images/node_network.png`, `wall_smash.mp4`

## Description

Break a model apart in Blender and take the result to a game engine.

H-Style RBD Nodes is a set of Geometry Nodes groups for rigid body destruction, made for game VFX: wall hits, explosions, ground cracks.

Connect a closed mesh to **RBD Material Fracture**, pick a Concrete, Glass or Wood pattern, connect it to **RBD Bullet Solver** and press **Bake**. Constraints hold the pieces together until something hits hard enough. After the bake you can scrub the timeline; the simulation only runs again when you bake again.

You can give pieces a starting velocity, delay the moment they let go, or push them around with Blender force fields. Select several objects that have a solver node and bake them together so their pieces collide.

Export as bone-animated FBX, rigid-body VAT (mesh, textures and JSON) or Alembic.

**Limits**

- Collisions use convex hulls, so hollows get filled in. A few hundred pieces is comfortable; 2000 or more can be slow.
- Pieces do not break further during the simulation.
- The Unity (URP) shader and playback scripts for VAT are a separate download.

[Examples and manual on GitHub](https://github.com/excifroge/H-Style-RBD-Nodes)
