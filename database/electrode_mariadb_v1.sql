-- QAC Auto Register / Electrode Lifecycle & Stock Control
-- MariaDB 10.6+ reference schema. utf8mb4 required.
CREATE DATABASE IF NOT EXISTS db_qac_electrode
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE db_qac_electrode;

CREATE TABLE IF NOT EXISTS electrode_type_master (
  electrode_code VARCHAR(32) PRIMARY KEY,
  description VARCHAR(255) NOT NULL DEFAULT '',
  spec VARCHAR(255) NOT NULL DEFAULT '',
  drawing_path VARCHAR(1024) NOT NULL DEFAULT '',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  CHECK (is_active IN (0,1))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS machine_positions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  line VARCHAR(64) NOT NULL,
  machine VARCHAR(128) NOT NULL,
  position VARCHAR(64) NOT NULL,
  status ENUM('ACTIVE','INACTIVE','DISABLED') NOT NULL DEFAULT 'ACTIVE',
  drawing_path VARCHAR(1024) NOT NULL DEFAULT '',
  snapshot_required TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY uq_machine_position(line,machine,position)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS electrode_compatibility (
  electrode_code VARCHAR(32) NOT NULL,
  position_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY(electrode_code,position_id),
  CONSTRAINT fk_compat_type FOREIGN KEY(electrode_code) REFERENCES electrode_type_master(electrode_code),
  CONSTRAINT fk_compat_pos FOREIGN KEY(position_id) REFERENCES machine_positions(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS electrode_units (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  base_no VARCHAR(96) NOT NULL UNIQUE,
  electrode_code VARCHAR(32) NOT NULL,
  serial_no VARCHAR(64) NOT NULL,
  current_reuse_cycle INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME(3) NOT NULL,
  KEY idx_unit_code(electrode_code),
  CONSTRAINT fk_unit_type FOREIGN KEY(electrode_code) REFERENCES electrode_type_master(electrode_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS electrode_cycles (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  unit_id BIGINT UNSIGNED NOT NULL,
  reuse_cycle INT UNSIGNED NOT NULL,
  display_no VARCHAR(128) NOT NULL UNIQUE,
  lifecycle_status ENUM('SPARE_ISSUED','PD_RECEIVED','LINE_STOCK','INSTALLED','WAITING_RETURN','COMPLETE','SCRAPPED','VOID') NOT NULL,
  issued_line VARCHAR(64) NULL,
  current_position_id BIGINT UNSIGNED NULL,
  spare_issued_at DATETIME(3) NULL,
  pd_received_at DATETIME(3) NULL,
  installed_at DATETIME(3) NULL,
  removed_at DATETIME(3) NULL,
  pd_returned_at DATETIME(3) NULL,
  completed_at DATETIME(3) NULL,
  initial_shot BIGINT UNSIGNED NULL,
  current_shot BIGINT UNSIGNED NULL,
  final_shot BIGINT UNSIGNED NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  UNIQUE KEY uq_unit_cycle(unit_id,reuse_cycle),
  KEY idx_cycle_status(lifecycle_status),
  KEY idx_cycle_line_status(issued_line,lifecycle_status),
  KEY idx_cycle_position_status(current_position_id,lifecycle_status),
  CONSTRAINT fk_cycle_unit FOREIGN KEY(unit_id) REFERENCES electrode_units(id),
  CONSTRAINT fk_cycle_position FOREIGN KEY(current_position_id) REFERENCES machine_positions(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS electrode_transactions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  cycle_id BIGINT UNSIGNED NOT NULL,
  event_type VARCHAR(48) NOT NULL,
  from_location VARCHAR(128) NOT NULL DEFAULT '',
  to_location VARCHAR(128) NOT NULL DEFAULT '',
  line VARCHAR(64) NOT NULL DEFAULT '',
  position_id BIGINT UNSIGNED NULL,
  shot BIGINT UNSIGNED NULL,
  actor_department VARCHAR(32) NOT NULL,
  actor_id VARCHAR(64) NOT NULL DEFAULT '',
  event_at DATETIME(3) NOT NULL,
  payload_json JSON NOT NULL,
  KEY idx_tx_cycle_time(cycle_id,event_at),
  KEY idx_tx_event_time(event_type,event_at),
  CONSTRAINT fk_tx_cycle FOREIGN KEY(cycle_id) REFERENCES electrode_cycles(id),
  CONSTRAINT fk_tx_position FOREIGN KEY(position_id) REFERENCES machine_positions(id)
) ENGINE=InnoDB;

-- Operational views intentionally exclude completed history from routine checks.
CREATE OR REPLACE VIEW v_electrode_active AS
SELECT c.*,u.base_no,u.electrode_code,u.serial_no
FROM electrode_cycles c
JOIN electrode_units u ON u.id=c.unit_id
WHERE c.lifecycle_status IN ('SPARE_ISSUED','PD_RECEIVED','LINE_STOCK','INSTALLED','WAITING_RETURN');

CREATE OR REPLACE VIEW v_electrode_line_balance AS
SELECT c.issued_line AS line,u.electrode_code,c.lifecycle_status,COUNT(*) AS qty
FROM electrode_cycles c
JOIN electrode_units u ON u.id=c.unit_id
WHERE c.lifecycle_status IN ('SPARE_ISSUED','PD_RECEIVED','LINE_STOCK','INSTALLED','WAITING_RETURN')
GROUP BY c.issued_line,u.electrode_code,c.lifecycle_status;
