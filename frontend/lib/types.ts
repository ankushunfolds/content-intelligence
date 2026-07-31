export type ChannelType = "own" | "competitor";

export interface TrackedChannel {
  id: number;
  tracked_id: number;
  type: ChannelType;
  youtube_channel_id: string;
  name: string;
  handle: string | null;
  url: string;
  thumbnail_url: string | null;
  subscriber_count: number;
  total_views: number;
  video_count: number;
  last_upload_at: string | null;
  last_ingested_at: string | null;
  median_views: number;
  videos_last_30d: number;
  breakouts_last_30d: number;
  upload_cadence_days: number | null;
  top_topics: string[];
}

export interface VideoIntelligence {
  topic: string | null;
  subtopic: string | null;
  format: string | null;
  angle: string | null;
  performance_ratio: number | null;
  performance_score: number | null;
  baseline_views: number | null;
  is_breakout: boolean;
}

export interface Video {
  id: number;
  youtube_video_id: string;
  channel_id: number;
  channel_name: string | null;
  title: string;
  published_at: string;
  views: number;
  likes: number;
  comments: number;
  duration_seconds: number;
  thumbnail_url: string | null;
  url: string;
  intelligence: VideoIntelligence | null;
}

export interface SignalBreakdown {
  raw: number;
  normalised: number;
  weight: number;
  contribution: number;
}

export interface Trend {
  id: number;
  topic: string;
  subtopic: string | null;
  trend_score: number;
  volume_growth: number;
  video_velocity: number;
  avg_performance: number;
  creator_count: number;
  video_count: number;
  breakout_count: number;
  top_format: string | null;
  components: {
    window_days?: number;
    recent_videos?: number;
    prior_videos?: number;
    weights?: Record<string, number>;
    signals?: Record<string, SignalBreakdown>;
  };
  detected_at: string;
}

export interface Opportunity {
  id: number;
  trend_id: number;
  topic: string;
  subtopic: string | null;
  momentum: number;
  top_format: string | null;
  why_it_matters: string;
  suggested_direction: string;
  evidence: {
    window_days: number;
    creator_count: number;
    video_count: number;
    breakout_count: number;
    volume_growth_pct: string;
    avg_performance: string;
    videos_per_day: number;
  };
  score_breakdown: Record<string, SignalBreakdown>;
}

export interface Breakout {
  id: number;
  video_id: number;
  channel_id: number;
  channel_name: string;
  title: string;
  url: string;
  thumbnail_url: string | null;
  views: number;
  views_display: string;
  performance: string;
  performance_ratio: number;
  baseline_display: string;
  topic: string | null;
  subtopic: string | null;
  format: string | null;
  published_at: string;
  why_it_matters: string;
}

export interface RisingTrend {
  trend_id: number;
  topic: string;
  subtopic: string | null;
  score: number;
  growth: string;
  avg_performance: string;
  creator_count: number;
  video_count: number;
  top_format: string | null;
}

export interface Activity {
  channel_id: number;
  channel_name: string;
  title: string;
  url: string;
  published_at: string;
  views_display: string;
  performance: string;
  is_breakout: boolean;
  subtopic: string | null;
}

export interface TodayIntelligence {
  headline: string | null;
  brief_date: string;
  generated_by: string;
  opportunities: Opportunity[];
  breakouts: Breakout[];
  rising_trends: RisingTrend[];
  competitor_activity: Activity[];
  stats: {
    tracked_channels?: number;
    opportunities?: number;
    breakouts?: number;
    trends?: number;
    window_days?: number;
  };
  data_mode: { youtube: string; llm: string };
}

export interface Brief {
  id: number;
  brief_date: string;
  generated_by: string;
  created_at: string;
  content: {
    headline: string;
    generated_at: string;
    opportunities: Opportunity[];
    competitor_highlights: Breakout[];
    rising_trends: RisingTrend[];
    stats: Record<string, number>;
  };
}

export interface RefreshResult {
  channels_ingested: number;
  videos_ingested: number;
  videos_classified: number;
  trends_detected: number;
  breakouts_detected: number;
  brief_date: string | null;
  duration_seconds: number;
}
