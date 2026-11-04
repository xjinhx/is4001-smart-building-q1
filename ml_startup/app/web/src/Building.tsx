import { useEffect, useMemo, useRef, useLayoutEffect } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Edges, Html, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import type { Zone } from './types'
import { LIFT_CORE, ZONE_SHAPES, type Pt } from './plan'

// A stylised massing of Chamchuri 5. Zones follow the CU-BEMS floor plan (see plan.ts); the
// 1.44:1 footprint is that plan's, and matches 11,700 m2 over seven floors.
const LENGTH = 46
const DEPTH = 32
const FLOOR_H = 3.6
const F3_Y = 8.2
const ROUND = 2.4

const CREAM = '#b9ae99'
const CREAM_DARK = '#8e8676'
const WALL_OFF = '#9a6a56'
const INERT = '#6d5a50'
const LIT = '#f2ad45'
const GLASS = '#5f8ea3'

function rounded(w: number, d: number, r: number) {
  const s = new THREE.Shape()
  const x = -w / 2, y = -d / 2
  s.moveTo(x + r, y)
  s.lineTo(x + w - r, y)
  s.quadraticCurveTo(x + w, y, x + w, y + r)
  s.lineTo(x + w, y + d - r)
  s.quadraticCurveTo(x + w, y + d, x + w - r, y + d)
  s.lineTo(x + r, y + d)
  s.quadraticCurveTo(x, y + d, x, y + d - r)
  s.lineTo(x, y + r)
  s.quadraticCurveTo(x, y, x + r, y)
  return s
}

// Plan polygon as an extrudable shape. Only the building's four outer corners are rounded.
function planShape(pts: Pt[]) {
  const P = pts.map(([u, v]) => new THREE.Vector2((u - 0.5) * LENGTH, -(v - 0.5) * DEPTH))
  const outer = pts.map(([u, v]) => (u === 0 || u === 1) && (v === 0 || v === 1))
  const s = new THREE.Shape()
  P.forEach((p, i) => {
    if (!outer[i]) {
      if (i === 0) s.moveTo(p.x, p.y)
      else s.lineTo(p.x, p.y)
      return
    }
    const prev = P[(i - 1 + P.length) % P.length], next = P[(i + 1) % P.length]
    const a = p.clone().add(prev.clone().sub(p).setLength(ROUND))
    const b = p.clone().add(next.clone().sub(p).setLength(ROUND))
    if (i === 0) s.moveTo(a.x, a.y)
    else s.lineTo(a.x, a.y)
    s.quadraticCurveTo(p.x, p.y, b.x, b.y)
  })
  s.closePath()
  return s
}

function Slab({ w, d, r, h, y, color = CREAM }: { w: number; d: number; r: number; h: number; y: number; color?: string }) {
  const geo = useMemo(() => new THREE.ExtrudeGeometry(rounded(w, d, r), { depth: h, bevelEnabled: false, curveSegments: 12 }), [w, d, r, h])
  return (
    <mesh geometry={geo} rotation={[-Math.PI / 2, 0, 0]} position={[0, y, 0]} castShadow receiveShadow>
      <meshStandardMaterial color={color} roughness={0.85} />
    </mesh>
  )
}

type ZoneProps = {
  pts: Pt[]; y: number; level: number; active: boolean; selected: boolean; hovered: boolean
  onHover: (on: boolean) => void; onSelect: () => void
}

function ZoneBlock({ pts, y, level, active, selected, hovered, onHover, onSelect }: ZoneProps) {
  const geo = useMemo(() => new THREE.ExtrudeGeometry(planShape(pts), { depth: FLOOR_H - 0.5, bevelEnabled: false, curveSegments: 12 }), [pts])
  const mat = useRef<THREE.MeshStandardMaterial>(null)
  const off = useMemo(() => new THREE.Color(active ? WALL_OFF : INERT), [active])
  const on = useMemo(() => new THREE.Color(LIT), [])
  // Eases towards the current load, so a restart reads as a zone coming on
  const shown = useRef(0)
  useFrame((_, dt) => {
    if (!mat.current) return
    shown.current += (level - shown.current) * Math.min(1, dt * 7)
    mat.current.color.copy(off).lerp(on, shown.current)
    mat.current.emissive.copy(on)
    mat.current.emissiveIntensity = shown.current * 0.35
  })
  return (
    <mesh
      geometry={geo} rotation={[-Math.PI / 2, 0, 0]} position={[0, y, 0]} castShadow receiveShadow
      onPointerOver={active ? (e) => { e.stopPropagation(); onHover(true); document.body.style.cursor = 'pointer' } : undefined}
      onPointerOut={active ? () => { onHover(false); document.body.style.cursor = '' } : undefined}
      onClick={active ? (e) => { e.stopPropagation(); onSelect() } : undefined}
    >
      <meshStandardMaterial ref={mat} roughness={0.7} />
      {(selected || hovered) && <Edges color={selected ? '#ededed' : '#a1a1a6'} threshold={30} />}
    </mesh>
  )
}

function Columns() {
  const ref = useRef<THREE.InstancedMesh>(null)
  const spots = useMemo(() => {
    const out: [number, number][] = []
    const nx = 11, nz = 7
    for (let i = 0; i <= nx; i++) { const x = -LENGTH / 2 + (i * LENGTH) / nx; out.push([x, DEPTH / 2 - 1], [x, -DEPTH / 2 + 1]) }
    for (let i = 1; i < nz; i++) { const z = -DEPTH / 2 + 1 + (i * (DEPTH - 2)) / nz; out.push([-LENGTH / 2, z], [LENGTH / 2, z]) }
    return out
  }, [])
  useLayoutEffect(() => {
    const m = new THREE.Matrix4()
    spots.forEach(([x, z], i) => { m.setPosition(x, 2, z); ref.current!.setMatrixAt(i, m) })
    ref.current!.instanceMatrix.needsUpdate = true
  }, [spots])
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, spots.length]} castShadow>
      <boxGeometry args={[1, 4, 1.4]} />
      <meshStandardMaterial color={INERT} roughness={0.9} />
    </instancedMesh>
  )
}

function SolarRoof({ y }: { y: number }) {
  const ref = useRef<THREE.InstancedMesh>(null)
  const panels = useMemo(() => {
    const out: [number, number][] = []
    for (let i = 0; i < 18; i++) for (let j = 0; j < 9; j++) out.push([-14.8 + i * 1.74, -10 + j * 2.5])
    return out
  }, [])
  useLayoutEffect(() => {
    const m = new THREE.Matrix4()
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), 0.14)
    const scale = new THREE.Vector3(1, 1, 1)
    panels.forEach(([x, z], i) => { m.compose(new THREE.Vector3(x, y + 0.35, z), q, scale); ref.current!.setMatrixAt(i, m) })
    ref.current!.instanceMatrix.needsUpdate = true
  }, [panels, y])
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, panels.length]} castShadow>
      <boxGeometry args={[1.62, 0.08, 2.3]} />
      <meshStandardMaterial color="#39434f" roughness={0.35} metalness={0.4} />
    </instancedMesh>
  )
}

const TARGET = new THREE.Vector3(0, 10, 0)

// Floor labels sit at whichever corner is furthest left on screen, so they never land on the building
function FloorTags() {
  const group = useRef<THREE.Group>(null)
  const v = useMemo(() => new THREE.Vector3(), [])
  const cx = LENGTH / 2 + 4, cz = DEPTH / 2 + 3
  useFrame(({ camera }) => {
    let best = Infinity
    for (const [sx, sz] of [[-1, -1], [-1, 1], [1, -1], [1, 1]]) {
      v.set(sx * cx, 16, sz * cz).project(camera)
      if (v.x < best) {
        best = v.x
        group.current?.position.set(sx * cx, 0, sz * cz)
      }
    }
  })
  return (
    <group ref={group}>
      {[3, 4, 5, 6, 7].map((f, fi) => (
        <Html key={f} position={[0, F3_Y + fi * FLOOR_H + 1.4, 0]} center zIndexRange={[5, 0]}>
          <span className="floor-tag">F{f}</span>
        </Html>
      ))}
    </group>
  )
}

// A visual cue only, from that day's sunrise, sunset, humidity and estimated cloud cover. It changes no figures.
const NIGHT = new THREE.Color('#16233d')
const TWILIGHT = new THREE.Color('#f2b48c')
const MORNING = new THREE.Color('#a9d6ef')
const HAZE = new THREE.Color('#e6ebea')
const OVERCAST = new THREE.Color('#ccd5da')
const SUN_LOW = new THREE.Color('#ffb27a')
const SUN_HIGH = new THREE.Color('#fff6e6')
const WHITE = new THREE.Color('#ffffff')
const NOON = new THREE.Color('#8fd0f7')

function Sky({ daylight, sun: sunHeight, humidity, cloud }: { daylight: number; sun: number; humidity: number; cloud: number }) {
  const { scene } = useThree()
  const hemi = useRef<THREE.HemisphereLight>(null)
  const sun = useRef<THREE.DirectionalLight>(null)
  const shown = useRef({ day: daylight, high: sunHeight, rh: humidity, cloud })
  const color = useMemo(() => new THREE.Color(NOON), [])
  useEffect(() => {
    scene.background = color
    return () => { scene.background = null }
  }, [scene, color])
  useFrame((_, dt) => {
    const k = Math.min(1, dt * 5), now = shown.current
    now.day += (daylight - now.day) * k
    now.high += (sunHeight - now.high) * k
    now.rh += (humidity - now.rh) * k
    now.cloud += (cloud - now.cloud) * k
    const cover = now.cloud / 100
    if (now.high < 0.35) color.copy(TWILIGHT).lerp(MORNING, now.high / 0.35)
    else color.copy(MORNING).lerp(NOON, (now.high - 0.35) / 0.65)
    color.lerp(HAZE, Math.min(1, Math.max(0, (now.rh - 55) / 40)) * 0.45)
    color.lerp(OVERCAST, cover * 0.75)
    color.lerp(NIGHT, 1 - now.day)
    if (hemi.current) {
      hemi.current.intensity = 0.7 + 0.4 * now.day + 0.8 * now.high
      hemi.current.color.copy(color).lerp(WHITE, 0.6)
    }
    if (sun.current) {
      sun.current.intensity = now.day * (0.15 + 1.45 * now.high) * (1 - 0.6 * cover)
      sun.current.color.copy(SUN_LOW).lerp(SUN_HIGH, now.high)
    }
  })
  return (
    <>
      <hemisphereLight ref={hemi} args={['#d6d8de', '#3a3633', 1.5]} />
      <directionalLight
        ref={sun} position={[40, 70, -50]} intensity={1.6} castShadow shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-70} shadow-camera-right={70} shadow-camera-top={70} shadow-camera-bottom={-70}
        shadow-camera-far={220}
      />
    </>
  )
}

// Keeps the whole building in frame at any panel size, whichever way it's been turned
function CameraFit() {
  const { camera, size } = useThree()
  useEffect(() => {
    const t = Math.tan(((camera as THREE.PerspectiveCamera).fov * Math.PI) / 360)
    const d = Math.max(30 / t, 42 / (t * (size.width / size.height)))
    const dir = camera.position.clone().sub(TARGET).normalize()
    camera.position.copy(TARGET).addScaledVector(dir, d)
  }, [camera, size])
  return null
}

function Tower({ zones, levels, selected, hovered, onHover, onSelect }: SceneProps) {
  const roofY = F3_Y + FLOOR_H * 5
  const find = (f: number, z: number) => zones.findIndex((v) => v.floor === f && v.zone === z)
  const wide = LENGTH + 1.4, deep = DEPTH + 1.4
  return (
    <group>
      <Slab w={LENGTH - 2} d={DEPTH - 2} r={1} h={4} y={0} color="#26211f" />
      <Columns />
      <Slab w={LENGTH + 5} d={DEPTH + 5} r={1} h={0.6} y={4} color={CREAM_DARK} />
      <Slab w={LENGTH} d={DEPTH} r={ROUND} h={3} y={4.6} color={INERT} />
      <Slab w={wide} d={deep} r={3} h={0.6} y={7.6} />
      {[3, 4, 5, 6, 7].map((f, fi) => {
        const y = F3_Y + fi * FLOOR_H
        return (
          <group key={f}>
            {[1, 2, 3, 4, 5].map((z) => {
              const j = find(f, z)
              return (
                <ZoneBlock
                  key={z} pts={ZONE_SHAPES[z]} y={y} level={j >= 0 ? levels[j] ?? 0 : 0} active={j >= 0}
                  selected={j === selected && j >= 0} hovered={j === hovered && j >= 0}
                  onHover={(on) => onHover(on ? j : null)} onSelect={() => onSelect(j)}
                />
              )
            })}
            <ZoneBlock pts={LIFT_CORE} y={y} level={0} active={false} selected={false} hovered={false} onHover={() => {}} onSelect={() => {}} />
            <Slab w={wide} d={deep} r={3} h={0.5} y={y + FLOOR_H - 0.5} />
          </group>
        )
      })}
      <FloorTags />
      {/* Stair glazing on the long side beside zone 3 and on the end, as in the reference image */}
      {[-7.6, 3].map((x) => (
        <mesh key={x} position={[x, 13.5, DEPTH / 2 + 0.3]} castShadow>
          <boxGeometry args={[1, 21, 0.8]} />
          <meshStandardMaterial color={CREAM} roughness={0.85} />
        </mesh>
      ))}
      <mesh position={[-2.3, 14, DEPTH / 2 + 0.05]}>
        <boxGeometry args={[2, 18, 0.5]} />
        <meshStandardMaterial color={GLASS} roughness={0.25} metalness={0.3} />
      </mesh>
      {[-1, 1].map((s) => (
        <mesh key={s} position={[s * (LENGTH / 2 + 0.3), 14, 0]}>
          <boxGeometry args={[0.5, 18, 2.6]} />
          <meshStandardMaterial color={GLASS} roughness={0.25} metalness={0.3} />
        </mesh>
      ))}
      <Slab w={wide} d={deep} r={3} h={1.1} y={roofY} />
      <SolarRoof y={roofY + 1.1} />
      <mesh position={[-19.5, roofY + 2.2, 0]} castShadow>
        <boxGeometry args={[5, 2.2, 16]} />
        <meshStandardMaterial color={CREAM_DARK} roughness={0.9} />
      </mesh>
      <mesh position={[19.5, roofY + 1.8, 0]} castShadow>
        <boxGeometry args={[4, 1.4, 14]} />
        <meshStandardMaterial color={CREAM_DARK} roughness={0.9} />
      </mesh>
    </group>
  )
}

function Site() {
  const road = '#303336', block = '#5a5d60'
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]} receiveShadow>
        <planeGeometry args={[400, 400]} />
        <meshStandardMaterial color="#46494c" roughness={1} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[68, 54]} />
        <meshStandardMaterial color="#55585b" roughness={1} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 41]} receiveShadow>
        <planeGeometry args={[400, 14]} />
        <meshStandardMaterial color={road} roughness={1} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[44, 0.01, 0]} receiveShadow>
        <planeGeometry args={[12, 400]} />
        <meshStandardMaterial color={road} roughness={1} />
      </mesh>
      {[[-66, 0, 30, 3.4, 46], [78, -8, 26, 2.4, 24], [6, -52, 58, 2.6, 16]].map(([x, z, w, h, d], i) => (
        <mesh key={i} position={[x, h / 2, z]} castShadow receiveShadow>
          <boxGeometry args={[w, h, d]} />
          <meshStandardMaterial color={block} roughness={1} />
        </mesh>
      ))}
    </group>
  )
}

type SceneProps = {
  zones: Zone[]; levels: number[]; selected: number | null; hovered: number | null; daylight: number; sun: number; humidity: number; cloud: number
  onHover: (j: number | null) => void; onSelect: (j: number) => void; onDeselect?: () => void
}

// Opens looking at zones 4, 1 and 2, the view that shows the most AC. Drag to see the other sides.
export default function Building(props: SceneProps) {
  return (
    <Canvas
      shadows dpr={[1, 2]} camera={{ position: [60, 36, -66], fov: 34, near: 1, far: 800 }}
      onCreated={({ camera }) => camera.lookAt(TARGET)}
      onPointerMissed={() => { props.onHover(null); props.onDeselect?.() }}
    >
      <Sky daylight={props.daylight} sun={props.sun} humidity={props.humidity} cloud={props.cloud} />
      <Site />
      <Tower {...props} />
      <CameraFit />
      <OrbitControls target={[0, 10, 0]} enablePan={false} enableZoom={false} minPolarAngle={0.5} maxPolarAngle={1.45} enableDamping />
    </Canvas>
  )
}
