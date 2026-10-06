"""Print the sockets / properties of the geometry nodes we plan to script. Dev helper."""
import bpy, json, sys
IDS = sys.argv[sys.argv.index("--") + 1:]
tree = bpy.data.node_groups.new("probe", "GeometryNodeTree")
base = {p.identifier for p in bpy.types.Node.bl_rna.properties}
def s(sock):
    return f"{sock.name}<{sock.identifier}>:{sock.bl_idname.replace('NodeSocket','')}" + ("" if sock.enabled else "(off)")
for idn in IDS:
    try:
        n = tree.nodes.new(idn)
    except Exception as e:
        print("NODE", idn, "ERROR", e); continue
    props = {}
    for p in n.bl_rna.properties:
        if p.identifier in base: continue
        if p.type == "ENUM":
            props[p.identifier] = [i.identifier for i in p.enum_items]
        else:
            props[p.identifier] = p.type
    print("NODE", idn, "|", n.bl_label)
    print("  in :", ", ".join(s(x) for x in n.inputs))
    print("  out:", ", ".join(s(x) for x in n.outputs))
    print("  props:", json.dumps(props))
# for-each zone pairing
fi = tree.nodes.new("GeometryNodeForeachGeometryElementInput")
fo = tree.nodes.new("GeometryNodeForeachGeometryElementOutput")
fi.pair_with_output(fo)
fo.domain = "POINT"
fo.input_items.new("VECTOR", "Seed")
fo.generation_items.new("INT", "Piece")
print("FOREACH paired")
print("  in.inputs :", ", ".join(s(x) for x in fi.inputs))
print("  in.outputs:", ", ".join(s(x) for x in fi.outputs))
print("  out.inputs :", ", ".join(s(x) for x in fo.inputs))
print("  out.outputs:", ", ".join(s(x) for x in fo.outputs))
print("  gen items:", [(i.name, i.socket_type, getattr(i, 'domain', None)) for i in fo.generation_items])
print("  main items:", [(i.name, i.socket_type) for i in fo.main_items])
ri = tree.nodes.new("GeometryNodeRepeatInput"); ro = tree.nodes.new("GeometryNodeRepeatOutput"); ri.pair_with_output(ro)
print("REPEAT in.inputs:", ", ".join(s(x) for x in ri.inputs), "| items:", [(i.name, i.socket_type) for i in ro.repeat_items])
