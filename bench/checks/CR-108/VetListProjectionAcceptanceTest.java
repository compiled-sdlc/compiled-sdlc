package org.springframework.samples.petclinic.vets.web;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.vets.model.Specialty;
import org.springframework.samples.petclinic.vets.model.Vet;
import org.springframework.samples.petclinic.vets.model.VetRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-108: the list is ordered by name and each element reports how
 * many specialties its vet has, with every existing field untouched.
 */
@WebMvcTest(VetResource.class)
@ActiveProfiles("test")
class VetListProjectionAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VetRepository vetRepository;

    private Specialty aSpecialty(String name) {
        Specialty specialty = new Specialty();
        specialty.setName(name);
        return specialty;
    }

    private Vet aVet(int id, String firstName, String lastName, String... specialties) {
        Vet vet = new Vet();
        vet.setId(id);
        vet.setFirstName(firstName);
        vet.setLastName(lastName);
        for (String name : specialties) {
            vet.addSpecialty(aSpecialty(name));
        }
        return vet;
    }

    @Test
    void shouldOrderByNameAndReportTheSpecialtyCount() throws Exception {
        given(vetRepository.findAll()).willReturn(List.of(
            aVet(1, "Rafael", "Ortega", "surgery"),
            aVet(2, "Helen", "Leary", "radiology", "dentistry"),
            aVet(3, "Adam", "Leary")
        ));

        mvc.perform(get("/vets").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(3))
            .andExpect(jsonPath("$[0].lastName").value("Leary"))
            .andExpect(jsonPath("$[0].firstName").value("Adam"))
            .andExpect(jsonPath("$[1].firstName").value("Helen"))
            .andExpect(jsonPath("$[2].lastName").value("Ortega"))
            .andExpect(jsonPath("$[0].specialtyCount").value(0))
            .andExpect(jsonPath("$[1].specialtyCount").value(2))
            .andExpect(jsonPath("$[2].specialtyCount").value(1));
    }

    @Test
    void shouldKeepEveryFieldTheListAlreadyCarried() throws Exception {
        given(vetRepository.findAll()).willReturn(List.of(
            aVet(7, "Helen", "Leary", "radiology")
        ));

        mvc.perform(get("/vets").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$[0].id").value(7))
            .andExpect(jsonPath("$[0].firstName").value("Helen"))
            .andExpect(jsonPath("$[0].lastName").value("Leary"))
            .andExpect(jsonPath("$[0].nrOfSpecialties").value(1))
            .andExpect(jsonPath("$[0].specialties[0].name").value("radiology"));
    }
}
