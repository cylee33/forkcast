export type ServiceFormat = "quick_service"|"fast_casual"|"casual_dining"|"fine_dining"|"bar"|"cafe"|"ghost_kitchen";
export type IncomeFit = "low"|"low_to_medium"|"medium"|"medium_to_high"|"high";
export type Catchment = "walk"|"transit"|"drive";
export type Archetype = "students"|"young_adults"|"office_workers"|"families"|"tourists"|"nightlife";
export type SubscoreKey = "D"|"C"|"T"|"A"|"S_spend"|"K"|"Sup";
export const SUBSCORE_KEYS: SubscoreKey[] = ["D","C","T","A","S_spend","K","Sup"];

export interface ConceptProfile {
  concept_name: string; cuisines: string[]; subcuisine: string[]; substitute_cuisines: string[];
  complementary_cuisines: string[]; service_format: ServiceFormat; price_tier: 1|2|3|4; avg_ticket_usd: number;
  dayparts: Partial<Record<"breakfast"|"lunch"|"dinner"|"late_night"|"weekend", number>>;
  customer_archetypes: Archetype[]; target_age_mix: Record<string, number>;
  dine_in_importance: number; takeout_importance: number; delivery_importance: number; parking_importance: number;
  pedestrian_importance: number; transit_importance: number; nightlife_importance: number; office_importance: number;
  university_importance: number; family_importance: number; visibility_importance: number;
  income_fit: IncomeFit; catchment: Catchment; catchment_tau_min: number; footprint_sqft: [number, number]; seats: number;
  supplier_types: string[]; direct_competitor_description: string; is_franchise: boolean;
  proposed_weights: Partial<Record<SubscoreKey, number>>; confidence: number; clarifying_questions: string[];
}
export interface Competitor { id: string; name: string; distance_m: number; similarity: number; rating: number|null; reviews: number|null; }
export interface Anchor { name: string; type: string; distance_m: number; }
export interface Zone {
  zone_id: number; name: string; total: number; best_h3: string; subscores: Record<SubscoreKey, number|null>;
  confidence: number; drivers: string[]; risks: string[]; gap: { demand: number; supply: number; gap: number };
  gap_flag: boolean; competitors_direct: Competitor[]; competitors_indirect: Competitor[]; anchors: Anchor[];
  est_rent_psf_yr: number|null; rent_confidence: number|null;
}
export interface CellProps extends Record<SubscoreKey, number|null> { h3: string; total: number; confidence: number; zone_id: number|null; }
export interface RecommendResponse {
  analysis_id: string; profile: ConceptProfile; weights: Record<SubscoreKey, number>;
  cells: GeoJSON.FeatureCollection<GeoJSON.Polygon, CellProps>; zones: Zone[]; backtest_rho: number|null;
}
