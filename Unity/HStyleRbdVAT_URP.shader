// SPDX-License-Identifier: CC0-1.0  (public domain: copy it into any project, including commercial games)
// Minimal Unity URP material for an H-Style RBD Nodes rigid-body VAT export. Use it as it is, or as a
// reference for calling HStyleRbdVAT() from your own shader. Keep HStyleRbdVAT.hlsl next to this file.
//
// Setup:
//   1. Import <name>_pos.exr and <name>_rot.exr with: sRGB off, Generate Mip Maps off, Filter Point,
//      Wrap Clamp, Compression None, Format RGBA Half (or RGBA Float), Non-Power of 2: None.
//   2. Create a material with this shader and assign both textures.
//   3. Copy width/height, frame_count, pivot_row and fps from <name>.json into the material.
//   4. Use <name>_mesh.fbx as the mesh. The lookup UV is its second UV set (TEXCOORD1) when the source
//      mesh had one UV map; see "lookup_uv_index" in the .json if it had more.
//   5. The mesh carries the bounds of the whole animation, so no renderer bounds need to be set.
//
// Auto Play loops the clip: the last frame is held for one frame, then it jumps back to the first.
// Destruction is a one-shot effect; drive _Frame yourself (Auto Play off) for anything else.
Shader "H-Style RBD Nodes/VAT Simple (URP)"
{
    Properties
    {
        _BaseColor ("Color", Color) = (0.7, 0.7, 0.7, 1)
        [NoScaleOffset] _PosTex ("Position Texture", 2D) = "black" {}
        [NoScaleOffset] _RotTex ("Rotation Texture", 2D) = "black" {}
        _VatSize ("Texture Size (width, height)", Vector) = (64, 64, 0, 0)
        _FrameCount ("Frame Count", Float) = 1
        _PivotRow ("Pivot Row", Float) = 1
        _Fps ("Frames Per Second", Float) = 24
        [Toggle] _AutoPlay ("Auto Play (loop)", Float) = 1
        _Frame ("Frame (Auto Play off)", Float) = 0
    }

    HLSLINCLUDE
    #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
    #include "HStyleRbdVAT.hlsl"

    TEXTURE2D(_PosTex);
    TEXTURE2D(_RotTex);
    SamplerState hrbd_point_clamp_sampler;

    CBUFFER_START(UnityPerMaterial)
        half4 _BaseColor;
        float4 _VatSize;
        float _FrameCount;
        float _PivotRow;
        float _Fps;
        float _AutoPlay;
        float _Frame;
    CBUFFER_END

    struct Attributes
    {
        float4 positionOS : POSITION;
        float3 normalOS   : NORMAL;
        float2 uvLookup   : TEXCOORD1;
        UNITY_VERTEX_INPUT_INSTANCE_ID
    };

    void HStyleRbdVertex(Attributes input, out float3 positionOS, out float3 normalOS)
    {
        float frame = _AutoPlay > 0.5 ? fmod(_Time.y * _Fps, max(_FrameCount, 1.0)) : _Frame;
        float4 rotation;
        HStyleRbdVAT(input.positionOS.xyz, input.normalOS, input.uvLookup.x, frame,
                   _PosTex, _RotTex, hrbd_point_clamp_sampler,
                   _VatSize.xy, _FrameCount, _PivotRow, positionOS, normalOS, rotation);
    }
    ENDHLSL

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "Queue" = "Geometry" }

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE _MAIN_LIGHT_SHADOWS_SCREEN
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 normalWS   : TEXCOORD0;
                float3 positionWS : TEXCOORD1;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            Varyings vert(Attributes input)
            {
                Varyings output;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
                float3 positionOS, normalOS;
                HStyleRbdVertex(input, positionOS, normalOS);
                output.positionWS = TransformObjectToWorld(positionOS);
                output.positionCS = TransformWorldToHClip(output.positionWS);
                output.normalWS = TransformObjectToWorldNormal(normalOS);
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                Light light = GetMainLight(TransformWorldToShadowCoord(input.positionWS));
                half3 n = normalize(input.normalWS);
                half3 lit = light.color * (saturate(dot(n, light.direction)) * light.shadowAttenuation);
                half3 ambient = SampleSH(n);
                return half4(_BaseColor.rgb * (lit + ambient), 1.0);
            }
            ENDHLSL
        }

        Pass
        {
            Name "ShadowCaster"
            Tags { "LightMode" = "ShadowCaster" }
            ZWrite On
            ZTest LEqual
            ColorMask 0

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #pragma multi_compile_vertex _ _CASTING_PUNCTUAL_LIGHT_SHADOW
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Shadows.hlsl"

            float3 _LightDirection;
            float3 _LightPosition;

            float4 vert(Attributes input) : SV_POSITION
            {
                UNITY_SETUP_INSTANCE_ID(input);
                float3 positionOS, normalOS;
                HStyleRbdVertex(input, positionOS, normalOS);
                float3 positionWS = TransformObjectToWorld(positionOS);
                float3 normalWS = TransformObjectToWorldNormal(normalOS);
                #if _CASTING_PUNCTUAL_LIGHT_SHADOW
                    float3 lightDirectionWS = normalize(_LightPosition - positionWS);   // point and spot lights
                #else
                    float3 lightDirectionWS = _LightDirection;                          // directional lights
                #endif
                float4 positionCS = TransformWorldToHClip(ApplyShadowBias(positionWS, normalWS, lightDirectionWS));
                #if UNITY_REVERSED_Z
                    positionCS.z = min(positionCS.z, positionCS.w * UNITY_NEAR_CLIP_VALUE);
                #else
                    positionCS.z = max(positionCS.z, positionCS.w * UNITY_NEAR_CLIP_VALUE);
                #endif
                return positionCS;
            }

            half4 frag() : SV_Target { return 0; }
            ENDHLSL
        }

        Pass
        {
            Name "DepthOnly"
            Tags { "LightMode" = "DepthOnly" }
            ZWrite On
            ColorMask R

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing

            float4 vert(Attributes input) : SV_POSITION
            {
                UNITY_SETUP_INSTANCE_ID(input);
                float3 positionOS, normalOS;
                HStyleRbdVertex(input, positionOS, normalOS);
                return TransformObjectToHClip(positionOS);
            }

            half4 frag() : SV_Target { return 0; }
            ENDHLSL
        }
    }
    FallBack Off
}
