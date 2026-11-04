// Floors 3 to 7 zone layout, traced from Fig. 2 of the CU-BEMS paper (Pipattanasomporn et al.,
// Scientific Data 2020). u runs left to right and v top to bottom of the drawing, both 0 to 1.
// The paper gives no compass direction, so which way this faces on the model is assumed.
export type Pt = [number, number]

export const ZONE_SHAPES: Record<number, Pt[]> = {
  4: [[0, 0], [0.39, 0], [0.39, 0.315], [0.493, 0.315], [0.493, 0.52], [0.23, 0.52], [0.23, 0.41], [0, 0.41]],
  1: [[0.395, 0], [1, 0], [1, 0.41], [0.566, 0.41], [0.566, 0.52], [0.493, 0.52], [0.493, 0.315], [0.395, 0.315]],
  5: [[0, 0.41], [0.23, 0.41], [0.23, 1], [0, 1]],
  3: [[0.23, 0.52], [0.563, 0.52], [0.563, 1], [0.23, 1]],
  2: [[0.566, 0.41], [1, 0.41], [1, 1], [0.625, 1], [0.625, 0.52], [0.566, 0.52]],
}
export const LIFT_CORE: Pt[] = [[0.563, 0.52], [0.625, 0.52], [0.625, 1], [0.563, 1]]
export const LABEL_AT: Record<number, Pt> = { 4: [0.19, 0.2], 1: [0.72, 0.2], 5: [0.115, 0.72], 3: [0.395, 0.76], 2: [0.81, 0.7] }
