# H-Style RBD Nodes: Rigid Body Destruction Nodes for Blender Geometry Nodes

[![license](https://img.shields.io/badge/license-GPL--3.0--or--later-green.svg)](#license)
[![blender](https://img.shields.io/badge/Blender-5.2%20LTS-green.svg)](#requirements)

**Docs** ([English](README.md), [日本語](README_JA.md), [中文](README_ZH.md))

*H-Style RBD Nodes* is a set of rigid body destruction nodes for Blender Geometry Nodes. Node names, inputs, outputs, and parameter groups follow H-Style.  
Connect a model to `RBD Material Fracture` to produce three streams: pieces, constraints, and collision proxies. Connect them through to `RBD Bullet Solver`, bake the motion to the timeline, then export it to a game engine. The extension is intended for mesh animation in game VFX: destruction, explosions, and ground cracking.

**Key Features**

* **H-Style nodes**: one task per node, with attributes passing data between nodes. You can insert your own nodes in the chain
* **Bake to the timeline**: simulation uses Blender's built-in Bullet solver and stores the result on the node. Scrubbing the timeline afterward does not rerun the simulation
* **Export to game engines**: export bone-animated FBX, rigid-body VAT, or Alembic; a shader and playback component for Unity (URP) are provided separately

Features include Concrete / Glass / Wood fracture patterns, using existing parts as pieces, building constraints from contacts, clustering, initial velocity, delayed activation, Blender force fields, and simulating multiple objects in the same rigid body world.  
The extension contains only Python code. It does not modify Blender or include binaries; node groups are generated on first use.

| Wall Impact | Ground Cracking | Explosion |
|---|---|---|
| ![](Docs/Images/01_wall_smash.gif) | ![](Docs/Images/02_ground_crack.gif) | ![](Docs/Images/03_explosion.gif) |

| Glass | Wooden Post | Brick Wall (Existing Parts) |
|---|---|---|
| ![](Docs/Images/04_glass.gif) | ![](Docs/Images/05_wood_post.gif) | ![](Docs/Images/06_brick_wall.gif) |

See below for details of each node.

> **This project is AI friendly.** I have prepared a handoff document for you: [AGENTS.md](AGENTS.md) (in English). Give it to your own AI to read, and it can explain this extension to you and modify it on its own.

## Contents

<details>
<summary>Details</summary>

- [Setup](#setup)
    - [Requirements](#requirements)
    - [Installation](#installation)
- [Usage](#usage)
    - [Create an RBD Network](#create-an-rbd-network)
    - [Adjust Parameters](#adjust-parameters)
    - [Add Nodes](#add-nodes)
    - [Bake](#bake)
- [Nodes](#nodes)
    - [Three Geometry Streams](#three-geometry-streams)
    - [RBD Material Fracture](#rbd-material-fracture)
    - [RBD Assemble](#rbd-assemble)
    - [RBD Constraints From Rules](#rbd-constraints-from-rules)
    - [RBD Configure](#rbd-configure)
    - [RBD Select](#rbd-select)
    - [RBD Constraint Properties](#rbd-constraint-properties)
    - [RBD Cluster](#rbd-cluster)
    - [RBD Exploded View](#rbd-exploded-view)
    - [RBD Bullet Solver](#rbd-bullet-solver)
- [Attributes](#attributes)
- [Initial Velocity and Force Fields](#initial-velocity-and-force-fields)
- [Simulate Multiple Objects Together](#simulate-multiple-objects-together)
- [Export](#export)
    - [Use in Unity](#use-in-unity)
    - [VAT Format](#vat-format)
- [Examples](#examples)
- [Limitations](#limitations)
- [Trademarks](#trademarks)
- [License](#license)

</details>

## Setup

#### Requirements
The extension supports the following environment.

* Blender 5.2 LTS or newer

The Unity shader and playback component used with VAT exports have been verified in the following environment.

* Unity 6 (6000.0 LTS)
* Universal Render Pipeline 17

#### Installation
Choose either of the following installation methods.

**Option 1: Drag and drop into Blender**

Drag the following link from your browser into the Blender window and confirm when prompted.

**[➜ Drag this link into Blender to install](https://raw.githubusercontent.com/excifroge/H-Style-RBD-Nodes/main/Repository/h_style_rbd_nodes.zip?repository=.%2Findex.json&blender_version_min=5.2.0)**

* First, go to **Edit > Preferences > System > Network** and enable **Allow Online Access**
* The first time you drag in the link, Blender asks whether to add this extension's repository. Confirm to start installation. You can then update to new versions in **Edit > Preferences > Get Extensions**
* This link is intended for dragging. Clicking it only downloads the zip

**Option 2: Install from a zip**

1. Download `h_style_rbd_nodes-x.y.z.zip` from the [Releases](https://github.com/excifroge/H-Style-RBD-Nodes/releases) page. Do not extract it
2. In Blender, open **Edit > Preferences > Get Extensions**, choose **Install from Disk** from the drop-down menu at the top right, and select the downloaded zip. You can also drag the downloaded zip file directly into the Blender window

After installing with either method, press `N` in the 3D Viewport to open the Sidebar and check that the **H-Style RBD** tab appears.

After installation, the **Add** menu in the Geometry Nodes editor contains an **RBD** submenu.

Screenshots and parameter names in this document use the English interface.  
Node names remain in English in every language. The extension includes interface translations only for Simplified Chinese. With Blender set to another language, node input names remain in English, except for common terms that Blender itself translates, such as Geometry and Density.

## Usage

#### Create an RBD Network
Select a closed mesh object and click **Fracture This Object** in the **H-Style RBD** tab of the Sidebar.

A Geometry Nodes modifier is added to the object, with `RBD Material Fracture` and `RBD Bullet Solver` already connected.

<p align="center">
  <img width="80%" src="Docs/Images/node_network.png" alt="RBD Network"><br>
  <font color="grey">A newly created RBD network</font>
</p>

If the model is already made of separate parts, such as bricks or planks, click **Use Its Loose Parts** instead.  
This creates a network of three nodes: `RBD Assemble`, `RBD Constraints From Rules`, and `RBD Bullet Solver`.

#### Adjust Parameters
RBD node parameters can be set either on the nodes or in the Sidebar. Both edit the same data.

<p align="center">
  <img width="45%" src="Docs/Images/ui_sidebar.png" alt="Sidebar"><br>
  <font color="grey">Node parameters displayed in the Sidebar</font>
</p>

Position parameters (Impact Point, Origin, Wave Origin, Center) have buttons such as **Impact Point from 3D Cursor** below them. These fill in the 3D Cursor's position after converting it to the object's local space.

#### Add Nodes
In the Geometry Nodes editor, choose **Add > RBD** and drop the node onto the link between existing nodes.  
Connect the [three geometry streams](#three-geometry-streams) between RBD nodes.

#### Bake
Click **Bake** at the bottom of the Sidebar.

Bullet cannot run during Geometry Nodes evaluation, so the `RBD Bullet Solver` node itself does not simulate.  
Once baked, the simulation result is stored on the node, which then outputs the baked motion. Changing upstream node parameters no longer changes the result shown; click **Re-Bake** to update it. Click the trash icon, **Free Bake**, to return to the live fracture result.

After baking, you can:

* Scrub the timeline: the simulation does not rerun, and upstream fracture nodes are no longer evaluated
* Move, rotate, scale, or duplicate the object: the entire destruction animation follows
* [Export](#export)

If baking fails, no data is changed and the previous bake remains usable.

## Nodes
There are 9 RBD nodes, described below in data-flow order.

#### Three Geometry Streams
Following H-Style, each node passes three geometry streams to the next.

<table width="100%">
<thead>
<tr><td><b>Socket</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td><b>Geometry</b></td><td>
The pieces themselves: the mesh used for rendering.
</td></tr>
<tr><td><b>Constraint Geometry</b></td><td>
A mesh containing only edges. Each edge represents a glue bond, with its endpoints at the centers of the two pieces it connects.
</td></tr>
<tr><td><b>Proxy Geometry</b></td><td>
The collision shapes. During simulation, each piece uses the convex hull of its points in this stream as its collision shape.<br>
Edit this stream to use simpler collision shapes.
</td></tr>
</tbody>
</table>

#### RBD Material Fracture
Cuts the model into pieces and generates constraint and proxy geometry. Corresponds to the node of the same name in H-Style.

<p align="center">
  <img width="30%" src="Docs/Images/Nodes/material_fracture_concrete.png" alt="RBD Material Fracture (Concrete)">
  <img width="30%" src="Docs/Images/Nodes/material_fracture_glass.png" alt="RBD Material Fracture (Glass)">
  <img width="30%" src="Docs/Images/Nodes/material_fracture_wood.png" alt="RBD Material Fracture (Wood)"><br>
  <font color="grey">RBD Material Fracture with Material Type set to Concrete, Glass, and Wood</font>
</p>

Parameters unused by the current Material Type are automatically hidden on the node.

<table width="100%">
<thead>
<tr><td colspan="3"><b>Input</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Geometry</b></td><td>
The model to fracture. It must be a closed mesh; see <a href="#limitations">Limitations</a> for details.
</td></tr>
<tr><td colspan="3"><b>Constraint Geometry</b> / <b>Proxy Geometry</b></td><td>
Upstream constraints and proxies are merged with those generated by this node and passed on. These inputs can be left unconnected.
</td></tr>
<tr><td colspan="3"><b>Extra Points</b></td><td>

<p>
Optional. Connect a point cloud or mesh.
</p>
<p>
<ul>
<li>Concrete, Wood: use these points as cell seed points instead of scattering them automatically</li>
<li>Glass: use the first point as the impact point</li>
</ul>
</p>
</td></tr>
<tr><td colspan="3"><b>Material Type</b></td><td>

<p>
Choose the fracture pattern from the following options.
</p>
<p>
<ul>
<li>Concrete: chunky pieces, with finer fracture near the impact point (default)</li>
<li>Glass: radial and concentric cracks around the impact point, cutting straight through a thin pane</li>
<li>Wood: long splinters along the grain</li>
</ul>
</p>
</td></tr>
<tr><td colspan="3"><b>Random Seed</b></td><td>
The random seed for the entire node.
</td></tr>
<tr><td colspan="3"><b>Impact Point</b></td><td>
Where the object is hit, specified in object space.<br>
Glass cracks start here; Concrete fractures more finely here.
</td></tr>
<tr><td colspan="3"><b>Primary Fracture</b></td><td>
Parameter group.
</td></tr>
<tr><td></td><td colspan="2"><b>Scatter Points</b></td><td>

<p>
<b>Shown only when Material Type is Concrete or Wood.</b>
</p>
<p>
Number of seed points, approximately one per piece. The default is 30.
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Scatter Seed</b></td><td>
Changes only the random seed for scattering points.
</td></tr>
<tr><td></td><td colspan="2"><b>Impact Bias</b></td><td>

<p>
<b>Shown only when Material Type is Concrete.</b>
</p>
<p>
The fraction of seed points concentrated around the impact point. Higher values produce finer pieces near it.
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Impact Radius</b></td><td>

<p>
<b>Shown only when Material Type is Concrete.</b>
</p>
<p>
The region in which those seed points are concentrated.
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Cut Through</b></td><td>

<p>
<b>Shown only when Material Type is Concrete.</b>
</p>
<p>
Every cut goes straight through the model along its thinnest axis. Intended for ground, slabs, and walls viewed from the front.
</p>
</td></tr>
<tr><td colspan="3"><b>Secondary Fracture</b></td><td>

<p>
<b>Shown only when Material Type is Concrete.</b>
</p>
<p>
Parameter group with an enable toggle. Fractures some pieces again to mix large and small pieces.
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Fracture Ratio</b></td><td>
The fraction of pieces to fracture again.
</td></tr>
<tr><td></td><td colspan="2"><b>Points per Piece</b></td><td>
Number of additional seed points in each piece selected for further fracture.<br>
The final piece count is approximately Scatter Points × (1 + Fracture Ratio × Points per Piece).
</td></tr>
<tr><td colspan="3"><b>Cracks</b></td><td>

<p>
<b>Shown only when Material Type is Glass.</b>
</p>
<p>
Parameter group.
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Radial Crack Number</b></td><td>
Number of cracks extending outward from the impact point.
</td></tr>
<tr><td></td><td colspan="2"><b>Concentric Crack Number</b></td><td>
Number of concentric crack rings around the impact point.
</td></tr>
<tr><td></td><td colspan="2"><b>Impact Spread</b></td><td>
The outermost distance the concentric cracks reach from the impact point.
</td></tr>
<tr><td colspan="3"><b>Grain</b></td><td>

<p>
<b>Shown only when Material Type is Wood.</b>
</p>
<p>
Parameter group.
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Fracture Direction</b></td><td>

<p>
Direction of the grain.
</p>
<p>
<ul>
<li>Auto: the model's longest axis (default)</li>
<li>X / Y / Z: the specified axis</li>
</ul>
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Splinter Length</b></td><td>
The length-to-width ratio of the splinters.
</td></tr>
<tr><td colspan="3"><b>Detail</b></td><td>
Parameter group with an enable toggle. Adds surface detail to cut faces.
</td></tr>
<tr><td></td><td colspan="2"><b>Detail Level</b></td><td>
Subdivision levels for cut faces. Each additional level multiplies their polygon count by 4; a value of 1 is recommended for game engines.
</td></tr>
<tr><td></td><td colspan="2"><b>Noise Amplitude</b> / <b>Frequency</b></td><td>
Height and frequency of the surface detail.
</td></tr>
<tr><td></td><td colspan="2"><b>Edge Fade</b></td><td>
Surface detail fades out over this distance from the model's original surface, keeping the exterior closed.
</td></tr>
<tr><td colspan="3"><b>Constraints</b></td><td>
Parameter group with an enable toggle. Generates constraints between neighboring pieces that share cut faces.
</td></tr>
<tr><td></td><td colspan="2"><b>Primary Strength</b></td><td>
The breaking threshold of the glue bonds. A bond breaks when the impact exceeds this threshold.
</td></tr>
<tr><td></td><td colspan="2"><b>Strength Variance</b></td><td>
Amount of random variation in strength.
</td></tr>
<tr><td></td><td colspan="2"><b>Scale by Contact Area</b></td><td>
When enabled, pieces sharing a smaller cut face have weaker bonds.
</td></tr>
<tr><td colspan="3"><b>Output</b></td><td>
Parameter group.
</td></tr>
<tr><td></td><td colspan="2"><b>Assign Inside Material</b> / <b>Inside Material</b></td><td>
Assigns a material to the cut faces.
</td></tr>
<tr><td></td><td colspan="2"><b>UV Map</b> / <b>Inside UV Scale</b></td><td>
Cut faces receive box-projected UVs, written to the specified UV map.
</td></tr>
<tr><td></td><td colspan="2"><b>Robust Boolean</b></td><td>
Always uses the slower exact Boolean solver. When disabled, it falls back to the exact solver only for pieces where the fast solver fails.
</td></tr>
<tr><td></td><td colspan="2"><b>Keep Vertex Group</b></td><td>

<p>
Name of a vertex group (or float attribute) on the model. Pieces retain it under the same name for selecting pieces downstream.
</p>
<p>
Vertex groups do not survive Boolean operations, so each vertex of the pieces samples the weight at the nearest location on the original model's surface.
</p>
</td></tr>
</tbody>
</table>

The model's original UVs, materials, and vertex colors are preserved.  
The pieces' exterior surfaces retain the original model's shading normals. Before the pieces move, they look like the intact model, with no visible seams between them.

<table width="100%">
<thead>
<tr><td><b>Output</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td><b>Geometry</b></td><td>The pieces. Writes the attributes <code>piece_id</code>, <code>inside</code>, <code>rbd_pivot</code>, and <code>rbd_rest</code>.</td></tr>
<tr><td><b>Constraint Geometry</b></td><td>The constraints. Writes the attributes <code>strength</code>, <code>area</code>, and <code>anchor</code>.</td></tr>
<tr><td><b>Proxy Geometry</b></td><td>The pieces without surface detail on the cut faces.</td></tr>
</tbody>
</table>

#### RBD Assemble
Treats each loose part (connected mesh island) as a piece without cutting. Corresponds to Assemble in H-Style.

Use this for models already made of parts: brick walls, planks, or hand-cut debris. First join all parts into one object (`Ctrl+J`).

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/assemble.png" alt="RBD Assemble"><br>
  <font color="grey">RBD Assemble</font>
</p>

This node has no parameters. The parts' original UVs, materials, and vertex groups remain unchanged.

<table width="100%">
<thead>
<tr><td><b>Output</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td><b>Geometry</b></td><td>The pieces. Writes the attributes <code>piece_id</code>, <code>inside</code>, <code>rbd_pivot</code>, and <code>rbd_rest</code>.</td></tr>
<tr><td><b>Constraint Geometry</b></td><td>Passes upstream constraints through unchanged. This node does not generate constraints; connect <a href="#rbd-constraints-from-rules">RBD Constraints From Rules</a> downstream.</td></tr>
<tr><td><b>Proxy Geometry</b></td><td>The pieces themselves.</td></tr>
</tbody>
</table>

#### RBD Constraints From Rules
Generates constraints between pieces whose surfaces are close to each other. Corresponds to the node of the same name in H-Style.

Works with pieces from any source. When placed after `RBD Material Fracture`, disable that node's **Constraints** to avoid generating two sets of constraints.

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/constraints_from_rules.png" alt="RBD Constraints From Rules"><br>
  <font color="grey">RBD Constraints From Rules</font>
</p>

<table width="100%">
<thead>
<tr><td colspan="3"><b>Input</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Search Radius</b></td><td>
Pieces whose surfaces are closer than this distance are glued together. The default is 2 centimeters.<br>
Parts with touching faces can be detected directly. If there are gaps, such as between bricks, set this slightly larger than the gap width.
</td></tr>
<tr><td colspan="3"><b>Strength</b> / <b>Strength Variance</b> / <b>Scale by Contact Area</b></td><td>
The same constraint parameters as in <a href="#rbd-material-fracture">RBD Material Fracture</a>.
</td></tr>
<tr><td colspan="3"><b>Keep Incoming Constraints</b></td><td>
When enabled, adds to the existing upstream constraints. When disabled, replaces them (default).
</td></tr>
<tr><td colspan="3"><b>Advanced</b></td><td>
Parameter group.
</td></tr>
<tr><td></td><td colspan="2"><b>Samples per Piece</b></td><td>
Number of points scattered on each piece's surface to find its neighbors. Higher values detect smaller contact surfaces.
</td></tr>
<tr><td></td><td colspan="2"><b>Seed</b></td><td>
Random seed for point scattering and strength variation.
</td></tr>
</tbody>
</table>

#### RBD Configure
Writes attributes on selected pieces: whether they participate in simulation, initial velocity, activation time, and physical properties. Corresponds to the node of the same name in H-Style.

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/configure.png" alt="RBD Configure"><br>
  <font color="grey">RBD Configure with all four parameter groups enabled</font>
</p>

Each of the four parameter groups has an enable toggle. Only enabled groups write attributes; unselected pieces keep their existing values.  
Chain multiple `RBD Configure` nodes to configure different pieces separately.

<table width="100%">
<thead>
<tr><td colspan="3"><b>Input</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Selection</b></td><td>
The pieces to configure. All are selected by default.<br>
Connect <a href="#rbd-select">RBD Select</a> or any Boolean field. A piece counts as selected when most of its vertices are selected.
</td></tr>
<tr><td colspan="3"><b>Set Active</b></td><td>
Parameter group with an enable toggle. Writes the <code>active</code> attribute.
</td></tr>
<tr><td></td><td colspan="2"><b>Active</b></td><td>
When disabled, selected pieces never move, but other pieces still collide with them. Use this to fix the bottom of a wall or the outer ring of the ground in place.
</td></tr>
<tr><td colspan="3"><b>Set Initial Velocity</b></td><td>
Parameter group with an enable toggle. Writes the <code>v</code> and <code>w</code> attributes. See <a href="#initial-velocity-and-force-fields">Initial Velocity and Force Fields</a> for details.
</td></tr>
<tr><td></td><td colspan="2"><b>Velocity Type</b></td><td>

<p>
<ul>
<li>Constant: the same velocity for every piece</li>
<li>Radial: outward from the origin, like an explosion (default)</li>
</ul>
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Velocity</b></td><td>

<p>
<b>Shown only when Velocity Type is Constant.</b>
</p>
<p>
Velocity in meters per second, with the direction specified in object space.
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Origin</b></td><td>

<p>
<b>The following parameters are shown only when Velocity Type is Radial.</b>
</p>
<p>
Center of the explosion, specified in object space.
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Speed</b></td><td>
Speed at the origin, in meters per second.
</td></tr>
<tr><td></td><td colspan="2"><b>Falloff Radius</b></td><td>
Speed falls to 0 at this distance. Set to 0 for no falloff.
</td></tr>
<tr><td></td><td colspan="2"><b>Up Bias</b></td><td>
How much the velocity direction tilts upward. 0 points directly away from the origin; 1 points straight up.
</td></tr>
<tr><td></td><td colspan="2"><b>Speed Variance</b></td><td>
Amount of random variation in speed.
</td></tr>
<tr><td></td><td colspan="2"><b>Spin</b></td><td>
Random angular velocity, in radians per second.
</td></tr>
<tr><td></td><td colspan="2"><b>Seed</b></td><td>
Random seed for speed variation and tumbling.
</td></tr>
<tr><td colspan="3"><b>Set Activation</b></td><td>
Parameter group with an enable toggle. Writes the <code>activate_time</code> attribute.<br>
Pieces remain still until activation, when they are handed over to the solver.
</td></tr>
<tr><td></td><td colspan="2"><b>Activation Type</b></td><td>

<p>
<ul>
<li>At Time: all pieces activate at the same time</li>
<li>Radial Wave: pieces activate in order of distance from the wave origin (default)</li>
</ul>
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Delay</b></td><td>
Seconds after the start frame.
</td></tr>
<tr><td></td><td colspan="2"><b>Wave Origin</b> / <b>Wave Speed</b></td><td>

<p>
<b>Shown only when Activation Type is Radial Wave.</b>
</p>
<p>
The wave's center (object space) and propagation speed (meters per second).
</p>
</td></tr>
<tr><td colspan="3"><b>Set Physical Properties</b></td><td>
Parameter group with an enable toggle. Writes the <code>density</code>, <code>friction</code>, and <code>bounce</code> attributes.
</td></tr>
<tr><td></td><td colspan="2"><b>Density</b> / <b>Friction</b> / <b>Bounce</b></td><td>
Pieces without these settings use the values on <a href="#rbd-bullet-solver">RBD Bullet Solver</a>.
</td></tr>
</tbody>
</table>

#### RBD Select
Outputs a selection (Boolean field) to connect to **Selection** on `RBD Configure` or `RBD Constraint Properties`. Equivalent to groups created by bounding boxes or attributes in H-Style.

<p align="center">
  <img width="24%" src="Docs/Images/Nodes/select_below_height.png" alt="RBD Select (Below Height)">
  <img width="24%" src="Docs/Images/Nodes/select_box.png" alt="RBD Select (Box)">
  <img width="24%" src="Docs/Images/Nodes/select_sphere.png" alt="RBD Select (Sphere)">
  <img width="24%" src="Docs/Images/Nodes/select_attribute.png" alt="RBD Select (Attribute)"><br>
  <font color="grey">RBD Select with Type set to Below Height, Box, Sphere, and Attribute</font>
</p>

Combine multiple selections with Blender's built-in Boolean Math node.

<table width="100%">
<thead>
<tr><td colspan="3"><b>Input</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Type</b></td><td>

<p>
Choose the selection method from the following options. All positions are specified in object space.
</p>
<p>
<ul>
<li>Below Height: pieces whose lowest point is at or below the specified height (default)</li>
<li>Box: pieces whose center is inside the box</li>
<li>Sphere: pieces whose center is inside the sphere</li>
<li>Attribute: pieces whose average vertex group weight or attribute value is at least the threshold</li>
</ul>
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Height</b></td><td>
<b>Shown only when Type is Below Height.</b>
</td></tr>
<tr><td></td><td colspan="2"><b>Center</b> / <b>Size</b></td><td>
<b>Shown only when Type is Box.</b> With Type set to Sphere, the node shows <b>Center</b> and <b>Radius</b>.
</td></tr>
<tr><td></td><td colspan="2"><b>Attribute</b> / <b>Threshold</b></td><td>

<p>
<b>Shown only when Type is Attribute.</b>
</p>
<p>
Name of a vertex group or attribute. For fractured pieces, enter the name used on <code>RBD Material Fracture</code> for <b>Keep Vertex Group</b>.
</p>
</td></tr>
<tr><td colspan="3"><b>Whole Pieces</b></td><td>
When enabled, evaluates whole pieces (default). When disabled, evaluates individual vertices.
</td></tr>
<tr><td colspan="3"><b>Invert</b></td><td>
Inverts the selection.
</td></tr>
</tbody>
</table>

#### RBD Constraint Properties
Changes the strength of selected constraints. Corresponds to the node of the same name in H-Style.

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/constraint_properties.png" alt="RBD Constraint Properties"><br>
  <font color="grey">RBD Constraint Properties</font>
</p>

<table width="100%">
<thead>
<tr><td colspan="3"><b>Input</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Selection</b></td><td>
The constraints to change, evaluated on the edges of the constraint geometry. All are selected by default.
</td></tr>
<tr><td colspan="3"><b>Operation</b></td><td>

<p>
<ul>
<li>Set To: sets the strength to the specified value (default)</li>
<li>Multiply By: multiplies the existing strength by the specified value</li>
</ul>
</p>
</td></tr>
<tr><td colspan="3"><b>Strength</b></td><td>
The value used for the operation above.
</td></tr>
</tbody>
</table>

#### RBD Cluster
Groups pieces into clusters and strengthens bonds within each cluster, producing a mix of large chunks and small pieces during destruction. Corresponds to the node of the same name in H-Style.

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/cluster.png" alt="RBD Cluster"><br>
  <font color="grey">RBD Cluster</font>
</p>

<table width="100%">
<thead>
<tr><td colspan="3"><b>Input</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Size</b></td><td>
Approximate size of a cluster.
</td></tr>
<tr><td colspan="3"><b>Jitter</b> / <b>Seed</b></td><td>
Irregularity of cluster shapes and the random seed.
</td></tr>
<tr><td colspan="3"><b>Strength Scale</b></td><td>
Multiplies the strength of constraints within a cluster by this value. The default is 10.
</td></tr>
</tbody>
</table>

Writes the <code>cluster</code> attribute on the pieces.

#### RBD Exploded View
Pushes pieces outward from the center to inspect the fracture result. Corresponds to Exploded View in H-Style.

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/exploded_view.png" alt="RBD Exploded View"><br>
  <font color="grey">RBD Exploded View</font>
</p>

Connect only **Geometry** to this node. After inspection, delete or mute it (select it and press `M`).

<table width="100%">
<thead>
<tr><td colspan="3"><b>Input</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Scale</b></td><td>
How far the pieces are pushed apart.
</td></tr>
</tbody>
</table>

To view constraints, `Ctrl+Shift+LMB`-click any RBD node's **Constraint Geometry** output in the node editor to connect it to a Viewer node.

#### RBD Bullet Solver
Simulates rigid bodies. Corresponds to the node of the same name in H-Style.

Simulation is run by the **Bake** button in the Sidebar; see [Bake](#bake) for details.

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/bullet_solver.png" alt="RBD Bullet Solver"><br>
  <font color="grey">RBD Bullet Solver</font>
</p>

The Bake button reads this node's settings, so they must be specified directly on the node rather than supplied through links from other nodes (except for the three geometry stream inputs).

<table width="100%">
<thead>
<tr><td colspan="3"><b>Input</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Start Frame</b> / <b>End Frame</b></td><td>
Frame range of the simulation.
</td></tr>
<tr><td colspan="3"><b>Time Scale</b></td><td>
Playback speed of the baked result. 0.5 gives slow motion.
</td></tr>
<tr><td colspan="3"><b>Simulation</b></td><td>
Parameter group.
</td></tr>
<tr><td></td><td colspan="2"><b>Bullet Substeps</b></td><td>
Solver steps per frame. Increase for fast-moving or thin pieces.
</td></tr>
<tr><td></td><td colspan="2"><b>Constraint Iterations</b></td><td>
Iterations used to solve collisions and constraints in each step.
</td></tr>
<tr><td></td><td colspan="2"><b>Glue Iterations</b></td><td>
Iterations used for each glue bond. Higher values make glued pieces stiffer but slow the simulation. Set to 0 to use Constraint Iterations.
</td></tr>
<tr><td colspan="3"><b>Properties</b></td><td>
Parameter group.
</td></tr>
<tr><td></td><td colspan="2"><b>Density</b> / <b>Bounce</b> / <b>Friction</b></td><td>
Values for pieces not configured by <a href="#rbd-configure">RBD Configure</a>. Density is in kilograms per cubic meter.
</td></tr>
<tr><td></td><td colspan="2"><b>Collision Padding</b></td><td>
Margin outside the collision shape.
</td></tr>
<tr><td></td><td colspan="2"><b>Linear Damping</b> / <b>Angular Damping</b></td><td>
Damping of linear and angular motion.
</td></tr>
<tr><td></td><td colspan="2"><b>Start Asleep</b></td><td>
When enabled, pieces remain still until hit by a collision.
</td></tr>
<tr><td colspan="3"><b>Collision</b></td><td>
Parameter group.
</td></tr>
<tr><td></td><td colspan="2"><b>Collision Objects</b></td><td>
Collection of objects that collide with the pieces. These objects follow their own animation.
</td></tr>
<tr><td></td><td colspan="2"><b>Ground Plane</b> / <b>Ground Height</b></td><td>
Enables the ground plane and sets its height in world space.
</td></tr>
<tr><td colspan="3"><b>Forces</b></td><td>
Parameter group.
</td></tr>
<tr><td></td><td colspan="2"><b>Gravity</b></td><td>
Gravitational acceleration.
</td></tr>
<tr><td></td><td colspan="2"><b>Force Fields</b></td><td>
When enabled, Blender force fields in the scene act on the pieces (default). See <a href="#initial-velocity-and-force-fields">Initial Velocity and Force Fields</a> for details.
</td></tr>
<tr><td></td><td colspan="2"><b>Field Weight</b></td><td>
Multiplies the strength of every force field by this value. Does not affect gravity.
</td></tr>
<tr><td></td><td colspan="2"><b>Limit To</b></td><td>
Only force fields in this collection act on the pieces. Leave empty to use all force fields in the scene.
</td></tr>
<tr><td colspan="3"><b>Cache</b></td><td>
Parameter group, collapsed by default. Filled in by the Bake button; usually does not need manual editing.
</td></tr>
<tr><td></td><td colspan="2"><b>Frame Offset</b></td><td>
Shifts the baked motion in time, in frames.
</td></tr>
</tbody>
</table>

## Attributes
RBD nodes pass data through the attributes below. Insert your own nodes to read or write them for controls not provided by the RBD nodes themselves.

Attributes on the pieces are stored on the point domain and averaged per piece during simulation.

<table width="100%">
<thead>
<tr><td><b>Attribute</b></td><td><b>Type</b></td><td><b>Written by</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="4"><b>Geometry</b></td></tr>
<tr><td><code>piece_id</code></td><td>Integer / Point</td><td>Material Fracture, Assemble</td><td>The piece a vertex belongs to. Equivalent to <code>name</code> in H-Style</td></tr>
<tr><td><code>inside</code></td><td>Boolean / Face</td><td>Material Fracture, Assemble</td><td>Whether the face is an interior surface created by cutting. Equivalent to the <code>inside</code> group in H-Style</td></tr>
<tr><td><code>rbd_pivot</code></td><td>Vector / Point</td><td>Material Fracture, Assemble</td><td>Center of the piece</td></tr>
<tr><td><code>rbd_rest</code></td><td>Vector / Point</td><td>Material Fracture, Assemble</td><td>Position before surface detail is added to the cut faces</td></tr>
<tr><td><code>active</code></td><td>Boolean / Point</td><td>Configure</td><td>False: does not move under simulation; acts only as an obstacle</td></tr>
<tr><td><code>v</code>, <code>w</code></td><td>Vector / Point</td><td>Configure</td><td>Velocity and angular velocity when handed over to the solver</td></tr>
<tr><td><code>activate_time</code></td><td>Float / Point</td><td>Configure</td><td>Seconds after the start frame when control is handed over to the solver</td></tr>
<tr><td><code>density</code>, <code>friction</code>, <code>bounce</code></td><td>Float / Point</td><td>Configure</td><td>A negative value means unset; uses the solver node's value</td></tr>
<tr><td><code>cluster</code></td><td>Integer / Point</td><td>Cluster</td><td>Cluster ID</td></tr>
<tr><td colspan="4"><b>Constraint Geometry</b></td></tr>
<tr><td><code>piece_id</code></td><td>Integer / Point</td><td>Material Fracture, Constraints From Rules</td><td>The piece connected to this end of the edge</td></tr>
<tr><td><code>strength</code></td><td>Float / Edge</td><td>Material Fracture, Constraints From Rules, Constraint Properties, Cluster</td><td>Bond breaking threshold</td></tr>
<tr><td><code>area</code></td><td>Float / Edge</td><td>Material Fracture, Constraints From Rules</td><td>Contact area</td></tr>
<tr><td><code>anchor</code></td><td>Vector / Edge</td><td>Material Fracture, Constraints From Rules</td><td>Contact position between the two pieces</td></tr>
</tbody>
</table>

## Initial Velocity and Force Fields
There are two ways to make pieces move. Use either on its own or both together.

<table width="100%">
<thead>
<tr><td></td><td><b>Initial Velocity</b></td><td><b>Force Fields</b></td></tr>
</thead>
<tbody>
<tr><td><b>Where to set it</b></td><td><code>RBD Configure</code>: <b>Set Initial Velocity</b></td><td>Add a Blender force field object to the scene (<code>Shift+A</code> > Force Field) and on <code>RBD Bullet Solver</code>, enable <b>Force Fields</b></td></tr>
<tr><td><b>How it acts</b></td><td>Sets velocity once, when the piece is handed over to the solver</td><td>Acts continuously throughout the simulation</td></tr>
<tr><td><b>Use cases</b></td><td>Instantaneous effects such as explosions and impacts</td><td>Continuous effects such as wind, turbulence, vortices, and drag</td></tr>
</tbody>
</table>

<p align="center">
  <img width="80%" src="Docs/Images/node_example_wind.png" alt="Initial velocity and force fields"><br>
  <font color="grey">A network with both initial velocity and force fields enabled (example 07)</font>
</p>

Force fields act in the same way as on Blender's built-in rigid bodies.

* Force field objects can be animated
* A force field of strength `S` applies `S ÷ frame rate` newtons to each piece, so `acceleration = strength × Field Weight ÷ (frame rate × piece mass)`
* For example, to give a 3-kilogram piece an acceleration of 10 meters/second² at 24 frames/second, a strength of approximately 720 is needed
* Lighter pieces accelerate faster
* The force acts at the piece's center of mass and does not itself cause rotation
* Pieces that have not yet activated, or have **Active** disabled, are unaffected by force fields
* Pieces with **Start Asleep** enabled wake immediately when acted on by a force field
* For pieces with initial velocity, force fields begin acting one frame later

## Simulate Multiple Objects Together
Each object has its own RBD network.

Select multiple objects with `RBD Bullet Solver` nodes, and the bake button becomes **Bake N Objects Together**.  
The objects are simulated in the same rigid body world, so their pieces collide with each other. Results are stored on each object's node and exported separately.

* Attribute data (initial velocity, simulation participation, activation time, constraints) remains independent for each object
* Solver settings come from the active object's `RBD Bullet Solver` node
* There are no constraints between pieces belonging to different objects
* All bakes succeed together, or all data remains unchanged

## Export
After baking, use the three export buttons at the bottom of the Sidebar.

<table width="100%">
<thead>
<tr><td><b>Button</b></td><td><b>Exported Data</b></td><td><b>Use</b></td></tr>
</thead>
<tbody>
<tr><td><b>Export FBX (Bones)</b></td><td>A skinned mesh with one bone per piece and baked animation</td><td>Use as standard skeletal animation in Unity or Unreal</td></tr>
<tr><td><b>Export VAT</b></td><td>Mesh <code>.fbx</code>, position and rotation textures <code>.exr</code>, and <code>.json</code></td><td>Many instances; playback on the GPU</td></tr>
<tr><td><b>Export Alembic</b></td><td>Animated mesh sampled every frame <code>.abc</code></td><td>Other DCC applications; offline rendering</td></tr>
</tbody>
</table>

FBX and VAT export the raw baked result, unaffected by **Time Scale** or **Frame Offset**. Alembic exports the result shown in the viewport.

FBX and VAT export options are listed below.

<table width="100%">
<thead>
<tr><td colspan="3"><b>Option</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Merge Unbroken Pieces</b></td><td>
When enabled (default), adjacent pieces that stay together throughout the animation are merged into one piece. All pieces that never move are also merged into one piece. Cut faces hidden between merged pieces are removed.<br>
This reduces the number of bones (or VAT texture columns) and polygons without changing the appearance.
</td></tr>
<tr><td></td><td colspan="2"><b>Merge Tolerance</b></td><td>
Pieces are merged only if no point on them deviates from the simulated result by more than this distance after merging. The default is 1 centimeter.
</td></tr>
<tr><td colspan="3"><b>Target</b></td><td>

<p>
<b>VAT only.</b>
</p>
<p>
<ul>
<li>Unity: converts data to Unity axes (default)</li>
<li>Blender Axes: keeps data in Blender axes</li>
</ul>
</p>
</td></tr>
<tr><td colspan="3"><b>Keep Rig in Scene</b></td><td>
<b>FBX only.</b> Keeps the generated armature and skinned mesh in the scene after export.
</td></tr>
</tbody>
</table>

#### Use in Unity

**Bone-Animated FBX**  
Add the file to your project. In the model's Import Settings, set **Animation > Anim. Compression** to **Off**.  
Alternatively, select the `.fbx` and run **Assets > H-Style RBD Nodes > Fix Bone FBX Import**.  
The default Keyframe Reduction can introduce deviations of 1 to 2 centimeters in rapidly tumbling pieces.

**VAT**  
First, place the four Unity files listed below anywhere under `Assets` in your project.  
Then place the exported files in a folder under `Assets`, select the exported `.json`, and run **Assets > H-Style RBD Nodes > Set Up VAT From Json**.  
Texture import settings, materials, and a prefab are generated automatically. Place the prefab directly in the scene.

The Unity files are not included in the extension and must be downloaded separately: from this repository's [`Unity`](Unity) folder, or as `h_style_rbd_unity-x.y.z.zip` from the [Releases](https://github.com/excifroge/H-Style-RBD-Nodes/releases) page.  
Keep only one copy in each Unity project.

<table width="100%">
<thead>
<tr><td><b>File</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td><code>HStyleRbdVAT_URP.shader</code></td><td>A ready-to-use URP shader with shadow and depth passes. Lighting uses only the main directional light and ambient light</td></tr>
<tr><td><code>HStyleRbdVAT.hlsl</code></td><td>Decoding functions to call from your own shader. Usage is documented at the top of the file</td></tr>
<tr><td><code>HStyleRbdVatSetup.cs</code></td><td>The setup menus described above (Editor script)</td></tr>
<tr><td><code>HStyleRbdVatPlayer.cs</code></td><td>Playback component (runtime script)</td></tr>
</tbody>
</table>

The prefab's `HStyleRbdVatPlayer` component controls one-shot playback.

<table width="100%">
<thead>
<tr><td><b>Property</b></td><td><b>Description</b></td></tr>
</thead>
<tbody>
<tr><td><b>Play On Enable</b></td><td>Automatically plays from the beginning when the object is enabled</td></tr>
<tr><td><b>Loop</b> / <b>Hold At End</b></td><td>Loop playback; seconds to hold the last frame of each loop</td></tr>
<tr><td><b>Speed</b></td><td>Playback speed</td></tr>
<tr><td><b>Break Particles</b></td><td>Optional. Assign a Particle System to emit particles at each crack's position as it opens</td></tr>
<tr><td><b>Particles Per Metre</b> / <b>Max Particles Per Crack</b> / <b>Min Crack Size</b></td><td>Larger cracks emit more particles; caps particles per crack; cracks smaller than this size emit none</td></tr>
</tbody>
</table>

For the Particle System assigned to **Break Particles**, set the Emission rate to 0 and disable Play On Awake.  
From scripts, use `Play()` and `Seek(seconds)`, or call `Advance(dt)` yourself after `Stop()`.

FBX and VAT meshes include vertex colors for per-piece shader effects. Values are linear, with 8-bit precision.

<table width="100%">
<thead>
<tr><td><b>Channel</b></td><td><b>Content</b></td></tr>
</thead>
<tbody>
<tr><td>R</td><td>A random value for each piece</td></tr>
<tr><td>G</td><td>When the piece starts moving. 0 is the first frame; 1 is the last frame or a piece that never moves</td></tr>
<tr><td>B</td><td>Distance from the piece to the impact point. 0 is nearest; 1 is farthest</td></tr>
<tr><td>A</td><td>1 for interior surfaces; 0 for original surfaces</td></tr>
</tbody>
</table>

The VAT `.json` also records fracture events: the time and position at which each pair of neighboring pieces separates, the crack size, and its opening speed (`event_times`, `event_positions`, `event_sizes`, `event_speeds`).  
The playback component uses this data to emit particles. You can also read it directly for VFX Graph, sound effects, or camera shake.

#### VAT Format
This extension uses its own format, `hrbd_vat_1`, which is incompatible with VAT shaders from other tools.

* Texture width is the smallest power of 2 at least as large as (piece count + 1); height is the smallest power of 2 at least as large as (frame count + 1)
* Row `k` holds baked frame `k`; the row indicated by `pivot_row` stores each piece's rest pivot
* The position texture's RGB stores the piece pivot's position for that frame; the rotation texture's RGBA stores the quaternion xyzw relative to the rest pose
* Coordinates are in the exported mesh's object space, converted to the target engine's axes (Unity: Blender's `(x, y, z)` becomes `(-x, z, -y)`)
* The u coordinate in the mesh's second UV channel (`TEXCOORD1`) is `(piece ID + 0.5) / texture width`
* Decode: `position = pivot for this frame + rotation(vertex - rest pivot)`; normals and tangents are only rotated
* With RGBA Half textures, error within a 10-meter range is approximately 2 to 3 millimeters

When configuring textures manually, disable sRGB and Generate Mip Maps in Import Settings. Set Filter Mode to Point, Wrap Mode to Clamp, Compression to None, and Non-Power of 2 to None.

## Examples
The `Examples` folder contains 7 baked examples. Open one, select the fractured object, and view its RBD network in the Geometry Nodes editor.

<table width="100%">
<thead>
<tr><td><b>File</b></td><td><b>Content</b></td><td><b>Nodes</b></td></tr>
</thead>
<tbody>
<tr><td><code>01_wall_smash</code></td><td>A ball smashing through a wall</td><td>Material Fracture → Cluster → Configure (+ Select) → Bullet Solver</td></tr>
<tr><td><code>02_ground_crack</code></td><td>Ground cracking</td><td>Material Fracture (Cut Through) → Configure (Set Initial Velocity + Set Activation) → Bullet Solver</td></tr>
<tr><td><code>03_explosion</code></td><td>Explosion</td><td>Material Fracture → Configure (Set Initial Velocity) → Bullet Solver</td></tr>
<tr><td><code>04_glass</code></td><td>Glass pierced by an impact</td><td>Material Fracture (Glass) → Configure (+ Select) → Bullet Solver</td></tr>
<tr><td><code>05_wood_post</code></td><td>A wooden post broken by an impact</td><td>Material Fracture (Wood) → Cluster → Configure (+ Select) → Bullet Solver</td></tr>
<tr><td><code>06_brick_wall</code></td><td>A wall built from existing bricks</td><td>Assemble → Constraints From Rules → Configure (+ two Select nodes) → Bullet Solver</td></tr>
<tr><td><code>07_explosion_wind</code></td><td>An explosion in the wind</td><td>Material Fracture → Configure (Set Initial Velocity) → Bullet Solver, plus wind and turbulence force fields</td></tr>
</tbody>
</table>

<p align="center">
  <img width="80%" src="Docs/Images/node_example_wall.png" alt="01_wall_smash"><br>
  <font color="grey">RBD network for 01_wall_smash</font>
</p>

<p align="center">
  <img width="80%" src="Docs/Images/node_example_bricks.png" alt="06_brick_wall"><br>
  <font color="grey">RBD network for 06_brick_wall. Two RBD Select nodes are combined with a Boolean Math node</font>
</p>

These examples are generated by `Examples/make_examples.py`.

## Limitations
* Verified only in Blender 5.2
* The Unity side has been verified only in Unity 6000.0 with URP 17; Unreal has not been verified
* `RBD Bullet Solver` does not simulate by itself. Re-bake after changing upstream parameters
* Models to fracture should be closed meshes. Holes, unwelded vertices, or single-layer surfaces produce open pieces; the Sidebar displays a warning
* Pieces use convex hull collision shapes, which fill in concavities
* Glue bonds are elastic: even unbroken contacts may open into small gaps under impact and then close again. Increase **Glue Iterations** to reduce this
* Bonds break independently; impacts do not propagate or attenuate through the constraint network
* Colliders whose shape changes over time (skeletal skinning, shape keys) produce excessively strong impacts
* A baked object is not a reliable collider for another bake. [Simulate multiple objects together](#simulate-multiple-objects-together) instead
* Force field strength is converted in the same way as for Blender's rigid bodies, requiring values much higher than usual. Only Wind and Force have been tested
* Position parameters use object space; only ground height uses world space
* Glass cracks are approximate: concentric cracks are segmented polylines, with no fine cracks branching from the main cracks
* Secondary fracture is approximate. There is no chipping or further fracturing during simulation
* Contact areas from `RBD Constraints From Rules` are estimates; very small contacts may not be detected
* With **Detail** enabled, vertices along the seam between cut faces and exterior surfaces coincide but are not welded
* Each piece becomes a Blender object during simulation. 500 pieces is comfortable; 2000 or more is noticeably slower
* Fracture events are exported only with VAT
* Scene unit scales other than 1 are ignored; one Blender unit is always treated as 1 meter
* Export overwrites files with the same name

For measured results, implementation details, and testing methods, see [AGENTS.md](AGENTS.md) (in English).

## Trademarks
Blender is a trademark of the Blender Foundation. Unity is a trademark of Unity Technologies.

## License
This extension is released under GPL-3.0-or-later.

The files in the [`Unity`](Unity) folder, `HStyleRbdVAT.hlsl`, `HStyleRbdVAT_URP.shader`, `HStyleRbdVatSetup.cs`, and `HStyleRbdVatPlayer.cs`, are released under CC0-1.0 and may be copied directly into any project.
