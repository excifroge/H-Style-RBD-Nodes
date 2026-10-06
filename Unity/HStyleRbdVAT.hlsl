// SPDX-License-Identifier: CC0-1.0  (public domain: copy it into any project, including commercial games)
// H-Style RBD Nodes rigid-body VAT, schema "hrbd_vat_1".
//
// Each piece of the mesh is moved as a rigid body: one texel per piece per frame.
//   position texture : RGB = pivot of the piece in object space (metres)
//   rotation texture : RGBA = quaternion xyzw, rotation relative to the rest pose
//   row k            : frame k.  Row _PivotRow holds the rest pivots.
//   lookup UV        : x = (piece + 0.5) / texture width   (the mesh UV layer named "VAT")
//
// Texture import: no sRGB, no mip maps, no compression, point filter, clamp.
// Values for the material come from the .json written next to the textures:
//   _VatSize = (width, height), _FrameCount = frame_count, _PivotRow = pivot_row, fps = fps
//
// Usage in a vertex shader (URP / built-in, with the usual Texture2D + SamplerState):
//   float frame = _Time.y * _Fps;                       // or any 0..FrameCount-1 value you drive yourself
//   HStyleRbdVAT(positionOS, normalOS, uvVAT.x, frame, _PosTex, _RotTex, sampler_PosTex,
//              _VatSize, _FrameCount, _PivotRow, positionOS, normalOS, rotation);
//   tangentOS.xyz = HStyleRbdRotate(rotation, tangentOS.xyz);   // only needed with normal maps
//
// The same function must run in every pass that draws the mesh (shadow caster, depth, motion vectors).
// Set the renderer bounds from animation_bounds_min / max in the .json, or the mesh gets culled.

#ifndef HSTYLE_RBD_VAT_INCLUDED
#define HSTYLE_RBD_VAT_INCLUDED

float3 HStyleRbdRotate(float4 q, float3 v)
{
    float3 t = 2.0 * cross(q.xyz, v);
    return v + q.w * t + cross(q.xyz, t);
}

void HStyleRbdVAT(float3 positionOS, float3 normalOS, float lookupU, float frame,
                Texture2D posTex, Texture2D rotTex, SamplerState pointClampSampler,
                float2 vatSize, float frameCount, float pivotRow,
                out float3 outPositionOS, out float3 outNormalOS, out float4 outRotation)
{
    float f = clamp(frame, 0.0, frameCount - 1.0);
    float f0 = floor(f);
    float f1 = min(f0 + 1.0, frameCount - 1.0);
    float blend = f - f0;

    float v0 = (f0 + 0.5) / vatSize.y;
    float v1 = (f1 + 0.5) / vatSize.y;
    float vp = (pivotRow + 0.5) / vatSize.y;

    float3 pivotRest = posTex.SampleLevel(pointClampSampler, float2(lookupU, vp), 0).xyz;
    float3 p0 = posTex.SampleLevel(pointClampSampler, float2(lookupU, v0), 0).xyz;
    float3 p1 = posTex.SampleLevel(pointClampSampler, float2(lookupU, v1), 0).xyz;
    float4 q0 = rotTex.SampleLevel(pointClampSampler, float2(lookupU, v0), 0);
    float4 q1 = rotTex.SampleLevel(pointClampSampler, float2(lookupU, v1), 0);

    // neighbouring frames are stored on the same side of the double cover, so a normalised
    // lerp is a good slerp here; the dot test only guards against edited data
    if (dot(q0, q1) < 0.0) q1 = -q1;
    float4 q = normalize(lerp(q0, q1, blend));
    float3 pivot = lerp(p0, p1, blend);

    outPositionOS = pivot + HStyleRbdRotate(q, positionOS - pivotRest);
    outNormalOS = HStyleRbdRotate(q, normalOS);
    outRotation = q;   // rotate tangent.xyz with HStyleRbdRotate(outRotation, tangentOS.xyz) for normal maps
}

#endif
