--
-- PostgreSQL database dump
--

\restrict l8t5C135RVjUqiAcwVRkW3yYM5z8Y6grBgTsbrZfd9jmc0xOkzCWOdM3aDgGYP3

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4 (Ubuntu 18.4-1.pgdg24.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: muzzle; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA muzzle;


--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: azure; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS azure WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION azure; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION azure IS 'azure extension for PostgreSQL service';


--
-- Name: pgaadauth; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgaadauth WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION pgaadauth; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgaadauth IS 'Microsoft Entra ID Authentication';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: enrollment; Type: TABLE; Schema: muzzle; Owner: -
--

CREATE TABLE muzzle.enrollment (
    id bigint NOT NULL,
    cattle_id bigint NOT NULL,
    embedding public.vector(512) NOT NULL,
    image_path text,
    quality_score real,
    captured_at timestamp with time zone,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: enrollment_id_seq; Type: SEQUENCE; Schema: muzzle; Owner: -
--

CREATE SEQUENCE muzzle.enrollment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: enrollment_id_seq; Type: SEQUENCE OWNED BY; Schema: muzzle; Owner: -
--

ALTER SEQUENCE muzzle.enrollment_id_seq OWNED BY muzzle.enrollment.id;


--
-- Name: identification_log; Type: TABLE; Schema: muzzle; Owner: -
--

CREATE TABLE muzzle.identification_log (
    id bigint NOT NULL,
    query_image_path text,
    matched_cattle_id bigint,
    similarity real,
    threshold_used real NOT NULL,
    decision character varying(20) NOT NULL,
    source character varying(30),
    model_version character varying(50),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: identification_log_id_seq; Type: SEQUENCE; Schema: muzzle; Owner: -
--

CREATE SEQUENCE muzzle.identification_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: identification_log_id_seq; Type: SEQUENCE OWNED BY; Schema: muzzle; Owner: -
--

ALTER SEQUENCE muzzle.identification_log_id_seq OWNED BY muzzle.identification_log.id;


--
-- Name: api_test; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_test (
    id bigint NOT NULL,
    message character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: api_test_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_test_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_test_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_test_id_seq OWNED BY public.api_test.id;


--
-- Name: cattle; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cattle (
    id bigint NOT NULL,
    national_id character varying(12) NOT NULL,
    barn_id character varying(50),
    status character varying(20) DEFAULT 'active'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    user_id bigint,
    ear_tag_number character varying(9),
    CONSTRAINT chk_cattle_ear_tag_number CHECK (((ear_tag_number IS NULL) OR ((ear_tag_number)::text ~ '^[0-9]{9}$'::text)))
);


--
-- Name: cattle_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cattle_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cattle_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cattle_id_seq OWNED BY public.cattle.id;


--
-- Name: cowow_devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cowow_devices (
    device_id text NOT NULL,
    device_name text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: device_claim_codes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_claim_codes (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    device_id text NOT NULL,
    code_hash text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: device_claim_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.device_claim_codes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: device_claim_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.device_claim_codes_id_seq OWNED BY public.device_claim_codes.id;


--
-- Name: device_commands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_commands (
    id bigint NOT NULL,
    device_id text NOT NULL,
    user_id bigint,
    actuator text NOT NULL,
    command_value jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    delivered_at timestamp with time zone
);


--
-- Name: device_commands_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.device_commands_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: device_commands_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.device_commands_id_seq OWNED BY public.device_commands.id;


--
-- Name: device_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_members (
    device_id text NOT NULL,
    user_id bigint NOT NULL,
    joined_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: device_owners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_owners (
    device_id text NOT NULL,
    user_id bigint NOT NULL,
    barn_name text DEFAULT '1번 축사'::text NOT NULL,
    registered_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: device_owners_release_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_owners_release_audit (
    audit_id bigint NOT NULL,
    device_id text NOT NULL,
    user_id bigint,
    barn_name text,
    original_registered_at timestamp with time zone,
    released_at timestamp with time zone DEFAULT now() NOT NULL,
    release_reason text DEFAULT 'manual reset'::text NOT NULL
);


--
-- Name: device_owners_release_audit_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.device_owners_release_audit_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: device_owners_release_audit_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.device_owners_release_audit_audit_id_seq OWNED BY public.device_owners_release_audit.audit_id;


--
-- Name: device_share_codes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_share_codes (
    id bigint NOT NULL,
    device_id text NOT NULL,
    invited_email text NOT NULL,
    code_hash text NOT NULL,
    created_by bigint NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    accepted_by bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: device_share_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.device_share_codes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: device_share_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.device_share_codes_id_seq OWNED BY public.device_share_codes.id;


--
-- Name: device_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.device_status (
    device_id text NOT NULL,
    firmware_version text,
    wifi_rssi integer,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    temperature double precision,
    humidity double precision,
    ammonia double precision,
    carbon_dioxide double precision,
    telemetry_at timestamp with time zone
);


--
-- Name: ear_tag_ocr_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ear_tag_ocr_results (
    id bigint NOT NULL,
    request_id character varying(64) NOT NULL,
    cattle_id bigint,
    detected_ear_tag_number character varying(9),
    confidence double precision DEFAULT 0.0 NOT NULL,
    ocr_status character varying(50) NOT NULL,
    verification character varying(100),
    requires_human_confirmation boolean DEFAULT false NOT NULL,
    vote_count integer DEFAULT 0 NOT NULL,
    evidence_local_path text,
    final_result_path text,
    raw_result jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_ear_tag_ocr_confidence CHECK (((confidence >= (0.0)::double precision) AND (confidence <= (1.0)::double precision))),
    CONSTRAINT chk_ear_tag_ocr_number CHECK (((detected_ear_tag_number IS NULL) OR ((detected_ear_tag_number)::text ~ '^[0-9]{9}$'::text))),
    CONSTRAINT chk_ear_tag_ocr_vote_count CHECK ((vote_count >= 0))
);


--
-- Name: ear_tag_ocr_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ear_tag_ocr_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ear_tag_ocr_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ear_tag_ocr_results_id_seq OWNED BY public.ear_tag_ocr_results.id;


--
-- Name: enrollment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enrollment (
    id bigint NOT NULL,
    cattle_id bigint NOT NULL,
    embedding public.vector(512) NOT NULL,
    image_path text,
    quality_score real,
    captured_at timestamp with time zone,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: enrollment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.enrollment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: enrollment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.enrollment_id_seq OWNED BY public.enrollment.id;


--
-- Name: identification_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.identification_log (
    id bigint NOT NULL,
    query_image_path text,
    matched_cattle_id bigint,
    similarity real,
    threshold_used real NOT NULL,
    decision character varying(20) NOT NULL,
    source character varying(30),
    model_version character varying(50),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: identification_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.identification_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: identification_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.identification_log_id_seq OWNED BY public.identification_log.id;


--
-- Name: native_login_tickets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.native_login_tickets (
    id bigint NOT NULL,
    ticket_hash character varying(64) NOT NULL,
    user_id bigint NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_native_login_ticket_hash_length CHECK ((char_length((ticket_hash)::text) = 64))
);


--
-- Name: native_login_tickets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.native_login_tickets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: native_login_tickets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.native_login_tickets_id_seq OWNED BY public.native_login_tickets.id;


--
-- Name: registered_devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.registered_devices (
    device_id text NOT NULL,
    user_id bigint NOT NULL,
    barn_name text,
    network_name text,
    claimed_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    provider character varying(30) NOT NULL,
    provider_user_id character varying(255) NOT NULL,
    name character varying(100),
    email character varying(255),
    profile_image_url text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: enrollment id; Type: DEFAULT; Schema: muzzle; Owner: -
--

ALTER TABLE ONLY muzzle.enrollment ALTER COLUMN id SET DEFAULT nextval('muzzle.enrollment_id_seq'::regclass);


--
-- Name: identification_log id; Type: DEFAULT; Schema: muzzle; Owner: -
--

ALTER TABLE ONLY muzzle.identification_log ALTER COLUMN id SET DEFAULT nextval('muzzle.identification_log_id_seq'::regclass);


--
-- Name: api_test id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_test ALTER COLUMN id SET DEFAULT nextval('public.api_test_id_seq'::regclass);


--
-- Name: cattle id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cattle ALTER COLUMN id SET DEFAULT nextval('public.cattle_id_seq'::regclass);


--
-- Name: device_claim_codes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_claim_codes ALTER COLUMN id SET DEFAULT nextval('public.device_claim_codes_id_seq'::regclass);


--
-- Name: device_commands id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_commands ALTER COLUMN id SET DEFAULT nextval('public.device_commands_id_seq'::regclass);


--
-- Name: device_owners_release_audit audit_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_owners_release_audit ALTER COLUMN audit_id SET DEFAULT nextval('public.device_owners_release_audit_audit_id_seq'::regclass);


--
-- Name: device_share_codes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_share_codes ALTER COLUMN id SET DEFAULT nextval('public.device_share_codes_id_seq'::regclass);


--
-- Name: ear_tag_ocr_results id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ear_tag_ocr_results ALTER COLUMN id SET DEFAULT nextval('public.ear_tag_ocr_results_id_seq'::regclass);


--
-- Name: enrollment id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment ALTER COLUMN id SET DEFAULT nextval('public.enrollment_id_seq'::regclass);


--
-- Name: identification_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identification_log ALTER COLUMN id SET DEFAULT nextval('public.identification_log_id_seq'::regclass);


--
-- Name: native_login_tickets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_login_tickets ALTER COLUMN id SET DEFAULT nextval('public.native_login_tickets_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: enrollment enrollment_pkey; Type: CONSTRAINT; Schema: muzzle; Owner: -
--

ALTER TABLE ONLY muzzle.enrollment
    ADD CONSTRAINT enrollment_pkey PRIMARY KEY (id);


--
-- Name: identification_log identification_log_pkey; Type: CONSTRAINT; Schema: muzzle; Owner: -
--

ALTER TABLE ONLY muzzle.identification_log
    ADD CONSTRAINT identification_log_pkey PRIMARY KEY (id);


--
-- Name: api_test api_test_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_test
    ADD CONSTRAINT api_test_pkey PRIMARY KEY (id);


--
-- Name: cattle cattle_national_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cattle
    ADD CONSTRAINT cattle_national_id_key UNIQUE (national_id);


--
-- Name: cattle cattle_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cattle
    ADD CONSTRAINT cattle_pkey PRIMARY KEY (id);


--
-- Name: cowow_devices cowow_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cowow_devices
    ADD CONSTRAINT cowow_devices_pkey PRIMARY KEY (device_id);


--
-- Name: device_claim_codes device_claim_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_claim_codes
    ADD CONSTRAINT device_claim_codes_pkey PRIMARY KEY (id);


--
-- Name: device_commands device_commands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_commands
    ADD CONSTRAINT device_commands_pkey PRIMARY KEY (id);


--
-- Name: device_members device_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_members
    ADD CONSTRAINT device_members_pkey PRIMARY KEY (device_id, user_id);


--
-- Name: device_owners device_owners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_owners
    ADD CONSTRAINT device_owners_pkey PRIMARY KEY (device_id);


--
-- Name: device_owners_release_audit device_owners_release_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_owners_release_audit
    ADD CONSTRAINT device_owners_release_audit_pkey PRIMARY KEY (audit_id);


--
-- Name: device_share_codes device_share_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_share_codes
    ADD CONSTRAINT device_share_codes_pkey PRIMARY KEY (id);


--
-- Name: device_status device_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_status
    ADD CONSTRAINT device_status_pkey PRIMARY KEY (device_id);


--
-- Name: ear_tag_ocr_results ear_tag_ocr_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ear_tag_ocr_results
    ADD CONSTRAINT ear_tag_ocr_results_pkey PRIMARY KEY (id);


--
-- Name: ear_tag_ocr_results ear_tag_ocr_results_request_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ear_tag_ocr_results
    ADD CONSTRAINT ear_tag_ocr_results_request_id_key UNIQUE (request_id);


--
-- Name: enrollment enrollment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment
    ADD CONSTRAINT enrollment_pkey PRIMARY KEY (id);


--
-- Name: identification_log identification_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identification_log
    ADD CONSTRAINT identification_log_pkey PRIMARY KEY (id);


--
-- Name: native_login_tickets native_login_tickets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_login_tickets
    ADD CONSTRAINT native_login_tickets_pkey PRIMARY KEY (id);


--
-- Name: native_login_tickets native_login_tickets_ticket_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_login_tickets
    ADD CONSTRAINT native_login_tickets_ticket_hash_key UNIQUE (ticket_hash);


--
-- Name: registered_devices registered_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registered_devices
    ADD CONSTRAINT registered_devices_pkey PRIMARY KEY (device_id);


--
-- Name: users uq_users_provider_account; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_provider_account UNIQUE (provider, provider_user_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_enroll_cattle; Type: INDEX; Schema: muzzle; Owner: -
--

CREATE INDEX idx_enroll_cattle ON muzzle.enrollment USING btree (cattle_id);


--
-- Name: idx_idlog_cattle_time; Type: INDEX; Schema: muzzle; Owner: -
--

CREATE INDEX idx_idlog_cattle_time ON muzzle.identification_log USING btree (matched_cattle_id, created_at DESC);


--
-- Name: idx_cattle_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cattle_user_id ON public.cattle USING btree (user_id);


--
-- Name: idx_device_claim_codes_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_device_claim_codes_lookup ON public.device_claim_codes USING btree (user_id, code_hash, used_at, expires_at);


--
-- Name: idx_device_commands_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_device_commands_pending ON public.device_commands USING btree (device_id, status, created_at);


--
-- Name: idx_device_members_one_device; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_device_members_one_device ON public.device_members USING btree (user_id);


--
-- Name: idx_device_owners_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_device_owners_user_id ON public.device_owners USING btree (user_id);


--
-- Name: idx_device_share_codes_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_device_share_codes_lookup ON public.device_share_codes USING btree (invited_email, code_hash, used_at, expires_at);


--
-- Name: idx_ear_tag_ocr_results_cattle_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ear_tag_ocr_results_cattle_id ON public.ear_tag_ocr_results USING btree (cattle_id);


--
-- Name: idx_ear_tag_ocr_results_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ear_tag_ocr_results_created_at ON public.ear_tag_ocr_results USING btree (created_at DESC);


--
-- Name: idx_ear_tag_ocr_results_detected_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ear_tag_ocr_results_detected_number ON public.ear_tag_ocr_results USING btree (detected_ear_tag_number);


--
-- Name: idx_enroll_cattle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enroll_cattle ON public.enrollment USING btree (cattle_id);


--
-- Name: idx_idlog_cattle_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_idlog_cattle_time ON public.identification_log USING btree (matched_cattle_id, created_at DESC);


--
-- Name: idx_native_login_tickets_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_native_login_tickets_expires_at ON public.native_login_tickets USING btree (expires_at);


--
-- Name: idx_registered_devices_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_registered_devices_user_id ON public.registered_devices USING btree (user_id);


--
-- Name: uq_cattle_ear_tag_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_cattle_ear_tag_number ON public.cattle USING btree (ear_tag_number) WHERE (ear_tag_number IS NOT NULL);


--
-- Name: enrollment enrollment_cattle_id_fkey; Type: FK CONSTRAINT; Schema: muzzle; Owner: -
--

ALTER TABLE ONLY muzzle.enrollment
    ADD CONSTRAINT enrollment_cattle_id_fkey FOREIGN KEY (cattle_id) REFERENCES public.cattle(id) ON DELETE CASCADE;


--
-- Name: identification_log identification_log_matched_cattle_id_fkey; Type: FK CONSTRAINT; Schema: muzzle; Owner: -
--

ALTER TABLE ONLY muzzle.identification_log
    ADD CONSTRAINT identification_log_matched_cattle_id_fkey FOREIGN KEY (matched_cattle_id) REFERENCES public.cattle(id);


--
-- Name: device_claim_codes device_claim_codes_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_claim_codes
    ADD CONSTRAINT device_claim_codes_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.cowow_devices(device_id) ON DELETE CASCADE;


--
-- Name: device_claim_codes device_claim_codes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_claim_codes
    ADD CONSTRAINT device_claim_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: device_commands device_commands_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_commands
    ADD CONSTRAINT device_commands_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: device_members device_members_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_members
    ADD CONSTRAINT device_members_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.cowow_devices(device_id) ON DELETE CASCADE;


--
-- Name: device_members device_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_members
    ADD CONSTRAINT device_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: device_owners device_owners_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_owners
    ADD CONSTRAINT device_owners_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.cowow_devices(device_id) ON DELETE CASCADE;


--
-- Name: device_owners device_owners_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_owners
    ADD CONSTRAINT device_owners_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: device_share_codes device_share_codes_accepted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_share_codes
    ADD CONSTRAINT device_share_codes_accepted_by_fkey FOREIGN KEY (accepted_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: device_share_codes device_share_codes_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_share_codes
    ADD CONSTRAINT device_share_codes_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: device_share_codes device_share_codes_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.device_share_codes
    ADD CONSTRAINT device_share_codes_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.cowow_devices(device_id) ON DELETE CASCADE;


--
-- Name: ear_tag_ocr_results ear_tag_ocr_results_cattle_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ear_tag_ocr_results
    ADD CONSTRAINT ear_tag_ocr_results_cattle_id_fkey FOREIGN KEY (cattle_id) REFERENCES public.cattle(id) ON DELETE SET NULL;


--
-- Name: enrollment enrollment_cattle_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment
    ADD CONSTRAINT enrollment_cattle_id_fkey FOREIGN KEY (cattle_id) REFERENCES public.cattle(id) ON DELETE CASCADE;


--
-- Name: cattle fk_cattle_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cattle
    ADD CONSTRAINT fk_cattle_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: identification_log identification_log_matched_cattle_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identification_log
    ADD CONSTRAINT identification_log_matched_cattle_id_fkey FOREIGN KEY (matched_cattle_id) REFERENCES public.cattle(id);


--
-- Name: native_login_tickets native_login_tickets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.native_login_tickets
    ADD CONSTRAINT native_login_tickets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: registered_devices registered_devices_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.registered_devices
    ADD CONSTRAINT registered_devices_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

\unrestrict l8t5C135RVjUqiAcwVRkW3yYM5z8Y6grBgTsbrZfd9jmc0xOkzCWOdM3aDgGYP3

